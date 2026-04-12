"""期货趋势跟踪"""
from ..base_strategy import BaseStrategy
from ..factory import register
from core.contracts import Signal, Action

@register("futures_donchian")
class FuturesDonchianStrategy(BaseStrategy):
    def __init__(self, entry_period: int = 20):
        super().__init__("futures_donchian", {"entry_period": entry_period})
        self.bars = {}
    def generate_signal(self, spec, bar: dict, context: dict):
        if str(spec.asset_class) != "FUTURE": return None
        sym = spec.symbol
        self.bars.setdefault(sym, []).append(bar)
        if len(self.bars[sym]) < self.params['entry_period']: return None
        recent = self.bars[sym][-self.params['entry_period']:]
        ch_high = max(b.get('high', b.get('close', 0)) for b in recent[:-1])
        if bar['close'] > ch_high:
            return Signal(symbol=sym, action=Action.BUY, strength=0.8, meta={"type":"donchian"})
        return None
