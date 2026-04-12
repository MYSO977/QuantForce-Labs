"""基础动量策略 (示例恢复)"""
from .base_strategy import BaseStrategy
from .factory import register
from core.contracts import Signal, Action
from core.instruments import get_contract, AssetClass
import numpy as np

@register("momentum")
class MomentumStrategy(BaseStrategy):
    """简单动量策略：价格突破过去 N 周期高点做多"""
    def __init__(self, threshold: float = 100.0, lookback: int = 20):
        super().__init__("momentum", {"threshold": threshold, "lookback": lookback})
        self.history = []

    def generate_signal(self, spec, bar: dict, context: dict):
        # 仅处理股票/ETF
        if spec.asset_class not in [AssetClass.STOCK, AssetClass.ETF, "STOCK", "ETF"]: 
            # 兼容之前的字符串或枚举类型
            if str(spec.asset_class) not in ["STOCK", "ETF"]: return None
            
        self.history.append(bar.get('close', 0))
        if len(self.history) < self.params['lookback']: return None
        
        current = bar.get('close', 0)
        past_max = max(self.history[-self.params['lookback']-1:-1])
        
        # 简单逻辑：当前价格 > 过去高点 * 阈值因子 (这里简化为绝对值或相对值)
        # 为演示方便：如果当前价 > threshold (100)，产生买入信号
        if current > self.params['threshold']:
            return Signal(symbol=spec.symbol, action=Action.BUY, strength=0.8, 
                          meta={"type": "momentum_breakout"})
        elif current < self.params['threshold'] * 0.95:
            return Signal(symbol=spec.symbol, action=Action.SELL, strength=0.8,
                          meta={"type": "momentum_reversal"})
        return None
