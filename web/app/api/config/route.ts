import { logger } from "@/lib/logger"
import { NextResponse } from 'next/server'
import { apiError } from "@/lib/api-error"
import { promises as fs } from 'fs'
import path from 'path'
import yaml from 'js-yaml'
import { z } from 'zod'

const SECRET_KEYS = ['api_key', 'api_secret', 'bot_token', 'chat_id'];

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

export async function GET() {
  try {
    const configPath = path.join(process.cwd(), '../config.yaml')
    const data = await fs.readFile(configPath, 'utf-8')
    const config = yaml.load(data)
    return NextResponse.json(stripSecrets(config))
  } catch (error) {
    logger.error('Failed to read config', { error: String(error) })
    return apiError('Failed to read config', 500)
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json()
    const parsed = ConfigSchema.safeParse(body)
    if (!parsed.success) {
      return apiError('Validation failed', 400, parsed.error.flatten())
    }
    const configPath = path.join(process.cwd(), '../config.yaml')
    const existing = yaml.load(await fs.readFile(configPath, 'utf-8')) as Record<string, unknown> || {}
    const merged = { ...existing, ...parsed.data }
    const yamlStr = yaml.dump(merged)
    await fs.writeFile(configPath, yamlStr, 'utf-8')
    return NextResponse.json({ success: true })
  } catch (error) {
    logger.error('Failed to write config', { error: String(error) })
    return apiError('Failed to write config', 500)
  }
}
