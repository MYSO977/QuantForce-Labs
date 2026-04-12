from typing import List
class StrategyAggregator:
    def __init__(self, strategies, position_store=None, strategy_weights=None, min_conflict_threshold=0.3):
        self.strategies = strategies
    def on_bar(self, instrument, bar, context) -> List:
        signals = []
        for s in self.strategies:
            try: signals.extend(s.on_bar(instrument, bar, context))
            except: pass
        return signals
