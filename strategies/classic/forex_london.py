"""外汇伦敦突破"""
from ..base_strategy import BaseStrategy
from ..factory import register
from core.contracts import Signal, Action
import datetime

@register("forex_london_breakout")
class ForexLondonBreakoutStrategy(BaseStrategy):
    def __init__(self, session_start: int = 8):
        super().__init__("forex_london_breakout", {"session_start": session_start})
    def generate_signal(self, spec, bar: dict, context: dict):
        if str(spec.asset_class) != "FOREX": return None
        return Signal(symbol=spec.symbol, action=Action.BUY, strength=0.5, meta={"type":"forex_london"})
