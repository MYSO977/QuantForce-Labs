"""ETF 动量策略"""
from ..base_strategy import BaseStrategy
from ..factory import register
from core.contracts import Signal, Action
import numpy as np, time

@register("etf_momentum")
class ETFMomentumStrategy(BaseStrategy):
    def __init__(self, lookback: int = 20, vol_target: float = 0.15):
        super().__init__("etf_momentum", {"lookback": lookback, "vol_target": vol_target})
        self.history = {}
    def generate_signal(self, spec, bar: dict, context: dict):
        if str(spec.asset_class) not in ["ETF", "STOCK"]: return None
        sym = spec.symbol
        self.history.setdefault(sym, []).append(bar.get('close', 0))
        if len(self.history[sym]) < self.params['lookback']: return None
        rets = np.diff(self.history[sym][-self.params['lookback']:])
        mom = np.mean(rets)
        if mom > 0.01:
            return Signal(symbol=sym, action=Action.BUY, strength=min(1.0, mom*10), meta={"type":"etf_mom", "mom":mom})
        return None
