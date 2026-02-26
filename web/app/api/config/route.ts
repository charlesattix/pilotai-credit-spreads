import { logger } from "@/lib/logger"
import { NextResponse } from 'next/server'
import { apiError } from "@/lib/api-error"
import { promises as fs } from 'fs'
import yaml from 'js-yaml'
import { z } from 'zod'
import { CONFIG_PATH } from "@/lib/paths"
import { verifyAuth } from "@/lib/auth"

const SECRET_KEYS = ['api_key', 'api_secret', 'bot_token', 'chat_id'];

/** Top-level config keys that may be modified via the API. */
const ALLOWED_TOP_LEVEL_KEYS = new Set([
  'tickers',
  'strategy',
  'risk',
  'alerts',
  'alpaca',
  'data',
  'logging',
  'backtest',
  'scanning',
  'paper_trading',
]);

/** Keys that must never appear anywhere in incoming config objects. */
const DANGEROUS_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

/**
 * Recursively strip keys that could cause prototype pollution
 * (`__proto__`, `constructor`, `prototype`).
 */
function stripDangerousKeys(obj: unknown): unknown {
  if (obj === null || obj === undefined) return obj;
  if (typeof obj !== 'object') return obj;
  if (Array.isArray(obj)) return obj.map(stripDangerousKeys);

  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
    if (DANGEROUS_KEYS.has(key)) continue;
    result[key] = stripDangerousKeys(value);
  }
  return result;
}

/** Keys whose string values represent file/directory paths and must be validated. */
const PATH_KEYS = new Set(['json_file', 'text_file', 'csv_file', 'file', 'report_dir']);

/**
 * Recursively check that no string value contains path traversal sequences
 * (`../`, `..\`, encoded variants) or absolute paths for path-like keys.
 * Returns the first offending key path, or null if clean.
 */
function findPathTraversal(obj: unknown, path = '', key = ''): string | null {
  if (typeof obj === 'string') {
    // Check for path traversal patterns (including URL-encoded)
    const decoded = decodeURIComponent(obj);
    if (decoded.includes('../') || decoded.includes('..\\') || obj.includes('../') || obj.includes('..\\')) {
      return path || '(root)';
    }
    // Reject absolute paths for file/directory config keys
    if (PATH_KEYS.has(key) && (obj.startsWith('/') || /^[A-Za-z]:[/\\]/.test(obj))) {
      return path || '(root)';
    }
    return null;
  }
  if (Array.isArray(obj)) {
    for (let i = 0; i < obj.length; i++) {
      const hit = findPathTraversal(obj[i], `${path}[${i}]`, key);
      if (hit) return hit;
    }
    return null;
  }
  if (obj !== null && typeof obj === 'object') {
    for (const [k, value] of Object.entries(obj as Record<string, unknown>)) {
      const hit = findPathTraversal(value, path ? `${path}.${k}` : k, k);
      if (hit) return hit;
    }
  }
  return null;
}

/**
 * Deep-merge `source` into `target`.
 * - If both sides are plain objects, recurse.
 * - Otherwise the source value replaces the target value
 *   (arrays and primitives are replaced, not concatenated).
 */
function deepMerge(
  target: Record<string, unknown>,
  source: Record<string, unknown>,
): Record<string, unknown> {
  const result: Record<string, unknown> = { ...target };
  for (const key of Object.keys(source)) {
    const tVal = target[key];
    const sVal = source[key];

    if (
      isPlainObject(tVal) &&
      isPlainObject(sVal)
    ) {
      result[key] = deepMerge(
        tVal as Record<string, unknown>,
        sVal as Record<string, unknown>,
      );
    } else {
      result[key] = sVal;
    }
  }
  return result;
}

function isPlainObject(val: unknown): val is Record<string, unknown> {
  return val !== null && typeof val === 'object' && !Array.isArray(val);
}

function stripSecrets(obj: unknown): unknown {
  if (obj === null || obj === undefined) return obj;
  if (typeof obj !== 'object') return obj;
  if (Array.isArray(obj)) return obj.map(stripSecrets);
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
    if (SECRET_KEYS.includes(key) && typeof value === 'string') {
      result[key] = value.startsWith('$') ? '${REDACTED}' : '***REDACTED***';
    } else {
      result[key] = stripSecrets(value);
    }
  }
  return result;
}

const TechnicalSchema = z.object({
  use_trend_filter: z.boolean().optional(),
  use_rsi_filter: z.boolean().optional(),
  use_support_resistance: z.boolean().optional(),
  fast_ma: z.number().int().positive().optional(),
  slow_ma: z.number().int().positive().optional(),
  rsi_period: z.number().int().positive().optional(),
  rsi_oversold: z.number().min(0).max(100).optional(),
  rsi_overbought: z.number().min(0).max(100).optional(),
}).optional();

const ConfigSchema = z.object({
  tickers: z.array(z.string().min(1).max(10)).optional(),
  strategy: z.object({
    min_dte: z.number().int().positive().optional(),
    max_dte: z.number().int().positive().optional(),
    manage_dte: z.number().int().positive().optional(),
    min_delta: z.number().min(0).max(1).optional(),
    max_delta: z.number().min(0).max(1).optional(),
    spread_width: z.number().positive().optional(),
    min_iv_rank: z.number().min(0).max(100).optional(),
    min_iv_percentile: z.number().min(0).max(100).optional(),
    technical: TechnicalSchema,
  }).optional(),
  risk: z.object({
    account_size: z.number().positive().optional(),
    max_risk_per_trade: z.number().min(0).max(100).optional(),
    max_positions: z.number().int().positive().optional(),
    profit_target: z.number().min(0).max(100).optional(),
    stop_loss_multiplier: z.number().positive().optional(),
  }).optional(),
  alerts: z.object({
    json_file: z.string().optional(),
    text_file: z.string().optional(),
    csv_file: z.string().optional(),
    telegram: z.object({
      enabled: z.boolean().optional(),
    }).optional(),
  }).optional(),
  alpaca: z.object({
    enabled: z.boolean().optional(),
  }).optional(),
  data: z.object({
    provider: z.enum(['yfinance', 'tradier', 'polygon']).optional(),
    tradier: z.object({}).optional(),
    polygon: z.object({ sandbox: z.boolean().optional() }).optional(),
    backtest_lookback: z.number().int().positive().optional(),
    use_cache: z.boolean().optional(),
    cache_expiry_minutes: z.number().int().positive().optional(),
  }).optional(),
  logging: z.object({
    level: z.enum(['DEBUG', 'INFO', 'WARNING', 'ERROR']).optional(),
    file: z.string().optional(),
    console: z.boolean().optional(),
  }).optional(),
  backtest: z.object({
    starting_capital: z.number().positive().optional(),
    commission_per_contract: z.number().min(0).optional(),
    slippage: z.number().min(0).optional(),
    generate_reports: z.boolean().optional(),
    report_dir: z.string().optional(),
  }).optional(),
});

export async function GET(request: Request) {
  const authErr = await verifyAuth(request); if (authErr) return authErr;
  try {
    const configPath = CONFIG_PATH
    const data = await fs.readFile(configPath, 'utf-8')
    const config = yaml.load(data, { schema: yaml.JSON_SCHEMA })
    return NextResponse.json(stripSecrets(config))
  } catch (error) {
    logger.error('Failed to read config', { error: String(error) })
    return apiError('Failed to read config', 500)
  }
}

export async function POST(request: Request) {
  const authErr = await verifyAuth(request); if (authErr) return authErr;
  try {
    const rawBody = await request.json()

    // SEC-INJ-04: Strip prototype-pollution keys before any processing
    const sanitizedBody = stripDangerousKeys(rawBody)

    // SEC-INJ-05: Reject any string values containing path traversal sequences
    const traversalHit = findPathTraversal(sanitizedBody)
    if (traversalHit) {
      return apiError(
        'Path traversal sequences are not allowed in config values',
        400,
        { field: traversalHit },
      )
    }

    // SEC-DATA-14 / ARCH-INT-09/23: Reject unknown top-level keys
    if (isPlainObject(sanitizedBody)) {
      const disallowed = Object.keys(sanitizedBody).filter(
        (k) => !ALLOWED_TOP_LEVEL_KEYS.has(k),
      )
      if (disallowed.length > 0) {
        return apiError(
          'Disallowed top-level config keys',
          400,
          { disallowed_keys: disallowed },
        )
      }
    }

    // Validate shape with Zod
    const parsed = ConfigSchema.safeParse(sanitizedBody)
    if (!parsed.success) {
      return apiError('Validation failed', 400, parsed.error.flatten())
    }

    const configPath = CONFIG_PATH
    const existing = yaml.load(await fs.readFile(configPath, 'utf-8'), { schema: yaml.JSON_SCHEMA }) as Record<string, unknown> || {}

    // SEC-DATA-14: Use deep merge instead of shallow spread
    const merged = deepMerge(existing, parsed.data as Record<string, unknown>)

    const yamlStr = yaml.dump(merged)
    await fs.writeFile(configPath, yamlStr, 'utf-8')
    return NextResponse.json({ success: true })
  } catch (error) {
    logger.error('Failed to write config', { error: String(error) })
    return apiError('Failed to write config', 500)
  }
}
