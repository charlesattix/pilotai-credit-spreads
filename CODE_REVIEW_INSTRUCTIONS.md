# 7 Pat Panel Code Review — Claude Code Instructions

This is your instruction set. Read it fully before doing anything.

You are conducting a comprehensive code review of `[SERVICE_NAME]` at `[PATH]` using 7 specialized panels. Your first action is to create `MASTERPLAN.md` at the project root. That file starts empty and becomes the living record of everything — every finding, every score, every revision. You and all subagents write to it continuously until the review is complete.

---

## Step 1: Create MASTERPLAN.md

Before launching any panels, create `MASTERPLAN.md` at the project root. It starts with only the header and an empty dashboard. The agents fill it in as they work.

The MASTERPLAN is the **single source of truth**. If it's not in MASTERPLAN.md, it didn't happen.

### MASTERPLAN Rules

1. **MASTERPLAN.md is created first** — before any review work begins
2. **Every agent reads MASTERPLAN.md** before starting their panel
3. **Every agent writes findings directly into MASTERPLAN.md** under their panel section — they create the section structure as they go
4. **Every agent updates the dashboard table** with their status and score in real-time
5. **Self-assessment is mandatory** — each panel scores its own work 1-10 with honest justification
6. **Score below 9 = not done** — the agent sets status to 🔁 REDO, documents what was missed, and goes again
7. **No inflated scores** — be brutally honest. A 10 means genuinely flawless. An 8 means real gaps remain. If you're unsure, score lower.
8. **Log every action** in the Revision Log at the bottom of MASTERPLAN.md

### MASTERPLAN Scoring Guide

```
10 — Flawless. Every search pattern checked. Every finding has file:line + code + impact + fix. Nothing missed.
 9 — Comprehensive. All critical paths covered. Minor gaps only (e.g., one search pattern unchecked).
 8 — Good but gaps. Some search patterns skipped, or evidence is thin on 1-2 findings. NOT DONE.
 7 — Significant gaps. Missing findings, generic content, or theoretical problems without evidence. NOT DONE.
 6 or below — Incomplete. Major sections unaddressed. NOT DONE.
```

**The threshold is 9. Anything below 9 means you go again.**

---

## Step 2: Launch All 7 Panels

Launch all 7 panels in parallel using the Task tool with:
- `subagent_type: "general-purpose"`
- `run_in_background: true`

Every panel prompt must include:
1. The **Base Instructions** (below)
2. The **panel-specific prompt** (below)
3. The **MASTERPLAN Protocol** (below)

### MASTERPLAN Protocol (Include in EVERY panel prompt)

```
MASTERPLAN PROTOCOL — READ THIS FIRST:

1. Read MASTERPLAN.md at the project root before doing anything.
2. Add your panel section to MASTERPLAN.md if it doesn't exist yet.
3. Update the dashboard table — set your status to 🔄 IN PROGRESS.
4. Do your review work. Write ALL findings directly into your section of MASTERPLAN.md.
   Each finding must have: Location (file:line), Evidence (code snippet), Problem (concrete impact), Fix (specific solution).
5. When done, add a Self-Assessment to your section:
   - Score (1-10, honest — see scoring guide in the instructions)
   - What was done well
   - What was missed or weak
   - If below 9: what specifically needs to be redone
6. Update the dashboard table with your score and status.
7. If score < 9: set status to 🔁 REDO, fix the gaps, re-score. Repeat until ≥ 9.
8. If score ≥ 9: set status to ✅ DONE.
9. Log every action (start, findings added, score, redo, done) in the Revision Log at the bottom.

IMPORTANT: Do not mark yourself ✅ DONE unless you genuinely earned a 9+. Review your own work
as if a senior engineer will audit it. If there are gaps, own them and fix them.
```

---

## Base Instructions (Apply to ALL Panels)

```
### CRITICAL REQUIREMENTS
1. **DISCOVERY BEFORE CONCLUSIONS**: Search 5+ patterns/terms before claiming anything is "missing"
2. **EVIDENCE-BASED**: Every finding MUST include file:line reference + code snippet
3. **MAX 5 P0/P1 ISSUES**: Quality over quantity — no generic findings
4. **VERIFY BEFORE CLAIMING "MISSING"**: State "I searched for X, Y, Z and found nothing"

### ANTI-PATTERNS TO AVOID
- Do NOT claim "Missing IaC" without checking: infra/, pulumi/, terraform/, cloudformation/, cdk/, k8s/
- Do NOT claim "Missing tests" without searching: tests/, test_*.py, *_test.py
- Do NOT make assumptions — READ the actual code
- Do NOT pad findings with generic observations like "consider adding more comments"
- Do NOT flag reasonable complexity in financial/trading systems as issues

### OUTPUT FORMAT
Every finding must include:
1. **Location:** `file:line`
2. **Evidence:** Code snippet (5-15 lines)
3. **Problem:** Concrete impact (not theoretical)
4. **Fix:** Specific solution with example code
```

---

## Panel Prompts

### Panel 1: Architecture Review

```
You are conducting a deep architecture review of [SERVICE_NAME] at [PATH].

### DISCOVERY PHASE
Search for these patterns to understand the architecture:
- Dependency injection: `container`, `inject`, `dependency`, `provider`, `factory`
- Repository pattern: `repository`, `repo`, `Repository`, `db/repositories`
- Service layer: `service`, `Service`, `services/`
- Event handling: `event`, `handler`, `EventHandler`, `queue`, `buffer`
- Circuit breaker: `circuit`, `breaker`, `CircuitBreaker`, `resilience`
- Adapter/Strategy patterns: `interface`, `Interface`, `adapter`, `broker`
- Transaction management: `transaction`, `commit`, `rollback`, `isolation`

### EVALUATION CRITERIA (Score 1-10 each)
1. Separation of Concerns — Are layers properly isolated?
2. Design Patterns — Repository, Strategy, Circuit Breaker appropriately used?
3. Dependency Injection — Properly implemented? Any tight coupling?
4. Data Flow — Clear flow from API → Service → Repository → Database?
5. Transaction Boundaries — Critical operations properly transactioned?
6. Error Propagation — Errors flow through proper channels?
7. Scalability — Components can scale independently?

### P0 INDICATORS
- Missing transaction boundaries for multi-step financial operations
- Tight coupling between core services
- Single points of failure without failover
- Race conditions in concurrent access patterns

### P1 INDICATORS
- Inconsistent patterns across similar components
- Over-engineering or under-engineering
- SOLID principle violations
```

---

### Panel 2: Code Quality Review

```
You are conducting a deep code quality review of [SERVICE_NAME] at [PATH].

### DISCOVERY PHASE
Search for these patterns:
- Large files: Check file sizes with `wc -l`, look for files >500 lines
- Code duplication: Similar function names, repeated blocks
- Type hints: `def.*\(.*:`, `-> `, `Optional`, `Union`
- Exception handling: `except Exception`, `except:`, specific exceptions
- Logging: `logger.`, log levels

### METRICS TO COLLECT
- Total lines of code (Python only)
- Average file size
- Largest files (top 5 with line counts)
- Number of `except Exception:` blocks
- Type hint coverage estimation

### EVALUATION CRITERIA (Score A-F)
1. Maintainability — Code clarity, naming, organization
2. Type Safety — Comprehensive type hints
3. DRY Principle — Code duplication minimized
4. Complexity — Cyclomatic complexity, nesting depth
5. Documentation — Docstrings where needed
6. Error Messages — Actionable and informative

### P0 INDICATORS
- Duplicated critical logic that could diverge
- Missing type hints in financial calculations
- Silent failures (empty except blocks)

### P1 INDICATORS
- Large files violating SRP (>500 lines)
- Deep nesting (>4 levels)
- God classes/functions
```

---

### Panel 3: Security Review

```
You are conducting a deep security review of [SERVICE_NAME] at [PATH].

### DISCOVERY PHASE — Search EXHAUSTIVELY

**SQL Injection:**
- `f"SELECT`, `f"INSERT`, `f"UPDATE`, `f"DELETE`
- `.format(`, `%s` in SQL context
- VERIFY: `$1`, `$2` parameterized queries

**Authentication:**
- `api_key`, `API_KEY`, `X-API-Key`, `Authorization`
- `secrets.compare_digest`, `hmac.compare_digest`
- Endpoints without auth dependencies

**Secrets Management:**
- `SecretStr`, `get_secret_value`
- Hardcoded: `password=`, `secret=`, `key=` followed by literals
- `.env` file contents

**Encryption:**
- `Fernet`, `encrypt`, `decrypt`, `PBKDF2`, `bcrypt`
- Key rotation patterns

### OWASP TOP 10 CHECKLIST
For each, search and document with evidence:
1. A01: Broken Access Control
2. A02: Cryptographic Failures
3. A03: Injection
4. A04: Insecure Design
5. A05: Security Misconfiguration
6. A06: Vulnerable Components
7. A07: Auth Failures
8. A08: Data Integrity
9. A09: Logging Failures
10. A10: SSRF

### P0 INDICATORS
- SQL injection vectors
- Authentication bypass
- Hardcoded secrets in code
- Timing attacks in auth comparison

### P1 INDICATORS
- Missing rate limiting on sensitive endpoints
- Overly permissive CORS
- Missing security headers
```

---

### Panel 4: Performance Review

```
You are conducting a deep performance review of [SERVICE_NAME] at [PATH].

### DISCOVERY PHASE

**Database Performance:**
- `SELECT *` vs specific columns
- Missing indexes: Check `migrations/sql/` for CREATE INDEX
- N+1 queries: loops with DB calls inside
- Connection pool: `pool`, `min_size`, `max_size`

**Algorithm Complexity:**
- Nested loops: `for.*for`, `while.*while`
- Self-joins in SQL
- Sorting without limits

**Caching:**
- `cache`, `Cache`, `redis`, `lru_cache`
- TTL settings, invalidation patterns

**Async Performance:**
- `await` in loops (sequential vs concurrent)
- `asyncio.gather`, `asyncio.create_task`
- Blocking calls in async context

### SCALE PROJECTIONS
For bottlenecks, estimate impact at:
- 100 operations/minute
- 1,000 operations/minute
- 10,000 operations/minute

### P0 INDICATORS
- O(n²) or worse in hot paths
- Missing connection pooling
- Blocking I/O in async context
- Unbounded growth (memory leaks)

### P1 INDICATORS
- Missing database indexes
- N+1 query patterns
- Missing pagination on large datasets
```

---

### Panel 5: Error Handling Review

```
You are conducting a deep error handling review of [SERVICE_NAME] at [PATH].

### DISCOVERY PHASE

**Exception Hierarchy:**
- Search `exceptions.py` for custom exceptions
- `class.*Error`, `class.*Exception`
- Inheritance from base exception

**Exception Handling:**
- `except Exception:` — overly broad
- `except:` — bare except (worst)
- `from e` — exception chaining
- `raise.*from`

**Retry & Resilience:**
- `retry`, `@retry`, `tenacity`, `backoff`
- Circuit breaker patterns
- Dead letter queue: `dlq`, `DLQ`
- `jitter`, `random.uniform` in retry delays

**Logging:**
- `logger.error`, `logger.exception`, `exc_info=True`
- Context in error messages

### RESILIENCE PATTERNS TO VERIFY
1. Retry with Jitter — Exponential backoff + random jitter
2. Circuit Breaker — OPEN/HALF_OPEN/CLOSED states
3. Dead Letter Queue — Failed messages preserved
4. Timeout Handling — Configurable timeouts
5. Graceful Degradation — Fallback behaviors

### P0 INDICATORS
- Silent failures: `except: pass`
- Missing exception chains (`raise X` without `from e`)
- Retrying non-retryable errors
- Missing jitter causing thundering herd

### P1 INDICATORS
- Inconsistent error response formats
- Missing context in error messages
- Custom exceptions not mapped to HTTP codes
```

---

### Panel 6: Testing Review

```
You are conducting a deep testing review of [SERVICE_NAME] at [PATH].

### DISCOVERY PHASE

**Test Infrastructure:**
- Test files: `tests/`, `test_*.py`
- Fixtures: `conftest.py`, `@pytest.fixture`
- Mocks: `@patch`, `MagicMock`, `AsyncMock`
- Test containers: `testcontainers`

**Test Types:**
- Unit: `test_*.py` in isolation
- Integration: `integration/`, database tests
- Contract: `contract/`, interface compliance
- Property-based: `hypothesis`, `@given`
- Load: `locust`, `load_test`
- E2E: `e2e/`, end-to-end flows

**Coverage:**
- `.coveragerc`, `--cov`, coverage thresholds

### CRITICAL MODULE COVERAGE
Verify dedicated tests exist for:
- `brokers/` — Broker implementations
- `services/` — Business logic
- `middleware/` — Auth, CSRF, rate limiting
- `db/repositories/` — Database operations
- `order_events/` — Event handling, DLQ

### P0 INDICATORS
- Untested critical module (>100 lines, financial operations)
- Missing integration tests for database
- No contract tests for external interfaces

### P1 INDICATORS
- Missing edge case coverage for financial calculations
- No property-based testing for complex logic
- Tests with hardcoded timing (sleep-based)
```

---

### Panel 7: Production Readiness Review

```
You are conducting a deep production readiness review of [SERVICE_NAME] at [PATH].

### ANTI-PATTERN WARNING
DO NOT claim "Missing IaC" without checking ALL of:
- `infra/`, `infrastructure/`
- `pulumi/`, `Pulumi.yaml`, `Pulumi.*.yaml`
- `terraform/`, `*.tf`
- `cloudformation/`, `*.cfn.yaml`
- `cdk/`, `cdk.json`
- `k8s/`, `kubernetes/`

### DISCOVERY PHASE

**Infrastructure as Code:**
- Pulumi: `infra/`, `Pulumi.yaml`, `index.ts`
- Terraform: `*.tf`
- CloudFormation: `*.cfn.yaml`
- Kubernetes: `k8s/`, `*.yaml` with `kind:`

**CI/CD:**
- `.github/workflows/`, `deploy*.yml`
- Deployment strategies: canary, blue-green, rolling
- Approval gates

**Monitoring:**
- Prometheus: `Counter`, `Gauge`, `Histogram`
- Grafana: `grafana/`, `dashboards/`
- Alerts: `alerting`, `alerts`
- Sentry: `sentry`, `SENTRY_DSN`

**DR & Backup:**
- Backup scripts, `BACKUP_RECOVERY.md`
- RTO/RPO documentation

### PRODUCTION CHECKLIST
Verify each with file:line evidence:
1. Health Checks — `/health`, `/ready`, `/live`
2. Graceful Shutdown — Signal handling, drain connections
3. Configuration — Environment-based, secrets management
4. Scaling — Auto-scaling config, resource limits
5. Deployment — Zero-downtime, rollback capability
6. Alerting — SLO-based alerts, severity levels

### P0 INDICATORS
- Missing health checks
- No graceful shutdown handling
- Secrets in code or git history
- No deployment rollback capability

### P1 INDICATORS
- Missing structured logging
- No alerting configuration
- Missing runbook/operational docs
```

---

## Step 3: Compile the Final Report

After all 7 panels show ✅ DONE (score ≥ 9) in the MASTERPLAN.md dashboard, add these sections to the bottom of MASTERPLAN.md:

1. **Executive Summary** — overall scores from each panel + top-line assessment
2. **P0 Issues (Critical)** — all critical findings compiled from all panels, with evidence
3. **P1 Issues (High Priority)** — all high-priority findings compiled, with evidence
4. **OWASP Top 10 Mapping** — security panel results mapped to OWASP categories
5. **Verified Strengths** — what the codebase does well (with evidence)
6. **Prioritized Recommendations** — action items ranked by effort vs. impact

Update the MASTERPLAN.md header status to 🟢 REVIEW DONE.

---

## Quality Gates (Entire Review)

- Each panel identifies MAX 5 P0/P1 issues
- Every finding must have file:line evidence
- No generic or theoretical findings
- All "missing" claims verified with search evidence
- **No panel is complete until its self-assessment score is ≥ 9**
- **Agents must be honest** — inflated scores defeat the entire purpose
- **MASTERPLAN.md is the only deliverable** — everything lives there
