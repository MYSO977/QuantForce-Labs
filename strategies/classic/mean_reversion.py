"""均值回归策略"""
from ..base_strategy import BaseStrategy
from ..factory import register
from core.contracts import Signal, Action
import numpy as np

@register("mean_reversion")
class MeanReversionStrategy(BaseStrategy):
    def __init__(self, lookback: int = 20, z_entry: float = 2.0):
        super().__init__("mean_reversion", {"lookback": lookback, "z_entry": z_entry})
        self.prices = {}
    def generate_signal(self, spec, bar: dict, context: dict):
        sym = spec.symbol
        self.prices.setdefault(sym, []).append(bar.get('close', 0))
        if len(self.prices[sym]) < self.params['lookback']: return None
        prices = np.array(self.prices[sym][-self.params['lookback']:])
        z = (bar['close'] - np.mean(prices)) / (np.std(prices) + 1e-6)
        if z < -self.params['z_entry']:
            return Signal(symbol=sym, action=Action.BUY, strength=min(1.0, -z/3), meta={"type":"mean_rev", "z":z})
        return None
