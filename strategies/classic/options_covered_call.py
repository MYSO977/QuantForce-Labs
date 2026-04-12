"""期权备兑策略"""
from ..base_strategy import BaseStrategy
from ..factory import register
from core.contracts import Signal, Action

@register("covered_call")
class CoveredCallStrategy(BaseStrategy):
    def __init__(self, target_delta: float = 0.30):
        super().__init__("covered_call", {"target_delta": target_delta})
    def generate_signal(self, spec, bar: dict, context: dict):
        if str(spec.asset_class) != "OPTION": return None
        return Signal(symbol=spec.symbol, action=Action.SELL, strength=0.4, meta={"type":"covered_call"})
