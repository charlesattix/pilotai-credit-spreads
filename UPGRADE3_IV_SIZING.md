# UPGRADE 3: IV-Scaled Position Sizing - Implementation Spec

## Logic Architecture

Replace static 2% risk with bounded IVR-based scalar:
- IVR < 20 (Low Edge): 1% risk (0.5x baseline)
- IVR 20-50 (Standard Edge): 2% risk (baseline)
- IVR > 50 (High Edge): Scale up linearly to 3% cap (1.5x baseline)

Enforce 40% max portfolio heat and 5-contract max.

## Production Code

```python
def calculate_dynamic_risk(account_value: float, iv_rank: float, current_portfolio_risk: float) -> float:
    base_risk_pct = 0.02
    max_portfolio_heat = 0.40

    if iv_rank < 20:
        target_risk_pct = base_risk_pct * 0.5
    elif iv_rank <= 50:
        target_risk_pct = base_risk_pct
    else:
        multiplier = min(1.5, 1.0 + ((iv_rank - 50) / 100.0))
        target_risk_pct = base_risk_pct * multiplier

    trade_dollar_risk = account_value * target_risk_pct

    if (current_portfolio_risk + trade_dollar_risk) > (account_value * max_portfolio_heat):
        available_risk_budget = (account_value * max_portfolio_heat) - current_portfolio_risk
        return max(0.0, available_risk_budget)

    return trade_dollar_risk

def get_contract_size(trade_dollar_risk: float, spread_width: float, credit_received: float) -> int:
    max_loss_per_contract = (spread_width - credit_received) * 100
    if max_loss_per_contract <= 0:
        return 0
    contracts = int(trade_dollar_risk // max_loss_per_contract)
    return min(contracts, 5)
```

## Integration Points
- Replace static risk calc in ml/position_sizer.py
- Feed IVR from ml/iv_analyzer.py (already exists)
- Track current_portfolio_risk from open positions in paper_trader.py
- Backtest engine needs same logic for accurate simulation
