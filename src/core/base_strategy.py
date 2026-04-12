"""BaseStrategy: 所有策略的抽象基类"""
from abc import ABC, abstractmethod
from typing import Optional, List
from .contracts import Signal

class BaseStrategy(ABC):
    strategy_id: str = "base"
    version: str = "1.0"
    is_primary: bool = False
    priority: int = 50
    shadow_mode: bool = False
    
    def __init__(self, name: str, params: dict = None):
        self.name = name
        self.params = params or {}
    
    @abstractmethod
    def generate_signal(self, spec, bar: dict, context: dict) -> Optional[Signal]:
        """核心信号生成逻辑"""
        raise NotImplementedError
    
    def on_bar(self, instrument: str, bar: dict, context: dict) -> List[Signal]:
        """统一入口: 解析合约 → 调用生成逻辑"""
        from .instruments import get_contract
        spec = get_contract(instrument)
        sig = self.generate_signal(spec, bar, context)
        return [sig] if sig else []
