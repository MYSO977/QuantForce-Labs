from core.contracts import RiskResult
def check_daily_loss(portfolio: dict, cfg: dict) -> RiskResult:
    pnl = portfolio.get("start_balance", 0) - portfolio.get("current_balance", 0)
    if pnl > cfg.get("daily_limit", 120): return RiskResult(False, f"daily_loss_exceeded: {pnl}")
    return RiskResult(True)

def pre_trade_risk(order, portfolio, cfg) -> RiskResult:
    return RiskResult(True)

def portfolio_risk_check(signals, portfolio, cfg) -> RiskResult:
    return RiskResult(True)
