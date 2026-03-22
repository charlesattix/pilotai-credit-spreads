# DB Sync Report — Paper Trading Accounts
**Generated:** 2026-03-12

---

## Summary

| Account | Alpaca Equity | Alpaca Positions | DB Open Trades | Status |
|---------|--------------|-----------------|----------------|--------|
| exp036  | $100,000.00  | 0               | 0 (7 needs_investigation) | Manual review needed |
| exp059  | $103,205.08  | 16 legs (8 spreads) | 8 open | CLEAN |
| exp154  | $101,253.98  | 20 legs (10 spreads) | 10 open | QTY MISMATCH |
| exp305  | $93,556.11   | 12 legs (6 spreads) | 6 open | QTY MISMATCH |

---

## Account Details

### exp036 — Manual Review Required (7 needs_investigation trades)

**Alpaca:** 0 positions, $100,000 cash (pristine account, no Alpaca activity).

**DB:** 7 trades in `needs_investigation` status (all `PT-*` prefixed IDs), 3 `closed`.

**Root Cause:** These `PT-*` trades were created by the old `PaperTrader` system (deleted Mar 5, 2026). That system simulated trades locally without submitting orders to Alpaca. All 7 have a blank `alpaca_client_order_id`. The reconciler correctly flagged them as `needs_investigation` because no corresponding Alpaca legs exist.

**What happened:** The reconciler ran on 2026-03-11 and found no matching Alpaca positions for any of the 7 trades (SPY C690–C698 Apr/May expirations, QQQ C632). It set status=`needs_investigation` with `exit_reason=legs_not_found_in_alpaca`.

**Action Required:**
- These 7 trades never existed in Alpaca and have no real P&L impact.
- Recommended: Manually set all 7 to `status='closed_manual'` with `exit_reason='legacy_paper_trader_purge'` and `pnl=0`.
- SQL:
  ```sql
  UPDATE trades
  SET status='closed_manual', exit_reason='legacy_paper_trader_purge', pnl=0, updated_at=datetime('now')
  WHERE id LIKE 'PT-%' AND status='needs_investigation';
  ```

---

### exp059 — CLEAN (no action needed)

**Alpaca:** 16 option legs (8 spreads) across SPY 2026-04-17 expiration.
**DB:** 8 open trades — all legs confirmed present in Alpaca with matching quantities.

**All 8 trades reconcile perfectly:**
| DB Trade ID | Type | Strikes | Contracts | Alpaca Match |
|-------------|------|---------|-----------|--------------|
| cs-722f307ea76a55d4 | bear_call | 699/704 | 25 | ✓ C699 -25 / C704 +25 |
| cs-51b98e69b80c2e16 | bull_put  | 652/647 | 24 | ✓ P652 -24 / P647 +24 |
| cs-31f42e8d2ed72250 | bear_call | 700/705 | 25 | ✓ C700 -25 / C705 +25 |
| cs-10725dd5169ce580 | bear_call | 703/708 | 25 | ✓ C703 -25 / C708 +25 |
| cs-a8b72e5554076f9c | bull_put  | 659/654 | 24 | ✓ P659 -24 / P654 +24 |
| cs-b736d8f0fd25c42b | bear_call | 702/707 | 25 | ✓ C702 -25 / C707 +25 |
| cs-5e5457c7b8129ddc | bull_put  | 650/645 | 23 | ✓ P650 -23 / P645 +23 |
| cs-8de0886415a3da4b | bear_call | 701/706 | 25 | ✓ C701 -25 / C706 +25 |

**Historical anomalies resolved (no action needed):**
- `cs-3f974c58db4bdbb4` (bear_call 695/700) and `cs-ad1638db027be3c2` (bear_call 696/701) are currently `failed_open` with `exit_reason=no_fill_reconciled`. These were temporarily marked `confirmed_filled` at 2026-03-12 00:02:42 by a reconciler pass that found `C700` and `C701` in Alpaca—but those symbols belong to `cs-31f42e8d2ed72250` and `cs-8de0886415a3da4b`. A later pass corrected the status to `failed_open`. The `failed_open` status is accurate.
- 6 `failed_open` trades total (4 with `alpaca_order_not_found`, 2 with `no_fill_reconciled`) — these represent scan attempts where orders were submitted but never filled, or order lookup failed. All are correctly closed.

**No fixes required.**

---

### exp154 — QTY MISMATCH (investigation required)

**Alpaca:** 20 option legs (10 spreads). All 10 DB open trades have matching legs in Alpaca.
**DB:** 10 open trades.

**4 qty mismatches identified:**

| Trade ID | Symbol | DB qty | Alpaca qty | Delta |
|----------|--------|--------|------------|-------|
| cs-5e5457c7b8129ddc | SPY260417P00650000 | 25 | **41** | +16 |
| cs-5e5457c7b8129ddc | SPY260417P00645000 | 25 | **41** | +16 |
| cs-8de0886415a3da4b | SPY260417C00701000 | 25 | **41** | +16 |
| cs-8de0886415a3da4b | SPY260417C00706000 | 25 | **41** | +16 |

**Root Cause:** Double-execution on two different orders with the same canonical trade ID (deterministic hash collision between accounts). The reconciler's `recover_orphans_from_order_history` ran and found two separate Alpaca orders for the same OCC symbol pair:
- `cs-5e5457c7b8129ddc` was recovered twice: once for 25 contracts (order `64c151d3`) and once for 16 contracts (order `bc744edc`). The upsert overwrote contracts to 25 (latest value won).
- `cs-8de0886415a3da4b` was recovered twice: once for 25 contracts (order `2aa3deac`) and once for 16 contracts (order `25dd5362`). The upsert overwrote contracts to 25.

So Alpaca has 41 (=25+16) contracts but the DB only shows 25. The 16-contract tranche was effectively "lost" from the DB's perspective.

**Also of note:** `reconcile-02fbb0f38242e104` is an open trade (bull_put 649/644, 16 contracts) that was inserted with a non-standard ID prefix (`reconcile-` instead of `cs-`), created at 2026-03-12 13:38:35. This was likely inserted by a manual or ad-hoc reconciliation script outside the standard flow. Alpaca has `SPY260417P00649000` (-16 short) and `SPY260417P00644000` (+16 long) confirming this position is real.

**Action Required:**
1. For the 2 duplicate-fill trades (`cs-5e5457c7b8129ddc` and `cs-8de0886415a3da4b`), update the DB `contracts` to match Alpaca (41):
   ```sql
   UPDATE trades SET contracts=41, updated_at=datetime('now')
   WHERE id IN ('cs-5e5457c7b8129ddc', 'cs-8de0886415a3da4b')
     AND db='data/pilotai_exp154.db';
   ```
2. The `reconcile-02fbb0f38242e104` trade is legitimate — no action needed.
3. **Root cause fix needed in code:** The execution engine should prevent duplicate orders for the same OCC symbol pair within a session. The deterministic `cs-` hash ID should be per-order (including a timestamp or a unique order UUID) rather than purely derived from spread parameters, so that two separately-filled orders on the same spread don't collide to a single DB row.

**No orphans — all Alpaca positions are accounted for by DB trades.**

---

### exp305 — QTY MISMATCH (minor, likely partial fills)

**Alpaca:** 12 option legs (6 spreads) across XLV, XLK, XLI tickers.
**DB:** 6 open trades.

**4 qty mismatches identified:**

| Trade ID | Symbol | DB qty | Alpaca qty | Delta |
|----------|--------|--------|------------|-------|
| cs-18524a23f401fd84 | XLV260417C00159000 | **19** | 18 | -1 |
| cs-18524a23f401fd84 | XLV260417C00164000 | **19** | 18 | -1 |
| cs-32dd9495feaf5bbd | XLV260417C00160000 | **18** | 17 | -1 |
| cs-32dd9495feaf5bbd | XLV260417C00165000 | **18** | 17 | -1 |

**Root Cause:** Partial fills. The DB recorded the intended contract count (19 and 18 respectively), but Alpaca only filled 18 and 17 contracts. The reconciler's `recover_orphans_from_order_history` pulled the `qty` from the Alpaca order, which may differ from the DB value if the order was partially filled and the unfilled portion cancelled.

Confirmation from reconciliation events:
- `cs-32dd9495feaf5bbd` recovered from Alpaca order `f437cfdd` with `contracts=17`.
- `cs-18524a23f401fd84` recovered from Alpaca order `ea70fdd1` with `contracts=18`.
- DB currently shows 18 and 19 (overstated by 1 each).

**Action Required:**
1. Update the DB contracts to match Alpaca actual fills:
   ```sql
   UPDATE trades SET contracts=18, updated_at=datetime('now')
   WHERE id='cs-18524a23f401fd84';
   -- Applied to data/pilotai_exp305.db

   UPDATE trades SET contracts=17, updated_at=datetime('now')
   WHERE id='cs-32dd9495feaf5bbd';
   -- Applied to data/pilotai_exp305.db
   ```
2. These are minor discrepancies (1 contract off). Risk calculation in the monitor will be very slightly overstated, but this is not critical.

**No orphans — all 12 Alpaca positions map exactly to the 6 DB trades.**

---

## What Was Fixed

No automatic fixes were applied during this diagnostic run. All identified issues require manual SQL or code-level action as described above.

## Fixes Applied (if `--fix` was run)

The `scripts/sync_db_from_alpaca.py --fix` flag will register any **orphan** Alpaca positions as `unmanaged` DB records. As of this report, there are **no orphans in any account**—the `--fix` flag has no effect on the current state.

---

## What Requires Manual Intervention

| Account | Issue | Priority | Action |
|---------|-------|----------|--------|
| exp036 | 7 `needs_investigation` legacy PT trades | Low | Run SQL to close as `legacy_paper_trader_purge` |
| exp154 | 2 trades with contracts=25 but Alpaca has 41 | Medium | Update DB contracts to 41 |
| exp154 | Code allows duplicate orders → same trade ID | High | Fix execution engine to include order UUID in hash |
| exp305 | 2 trades with DB qty overstated by 1 | Low | Update DB contracts to match Alpaca fill |

---

## Tool

Run diagnostics at any time:
```bash
# Report only
python3 scripts/sync_db_from_alpaca.py

# Single account
python3 scripts/sync_db_from_alpaca.py --account exp154

# Register orphans (no-op currently, useful for future orphan scenarios)
python3 scripts/sync_db_from_alpaca.py --fix
```
