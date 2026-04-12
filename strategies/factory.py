"""策略工厂：动态加载 + 注册表管理"""
from typing import List, Dict, Type
from .base_strategy import BaseStrategy

_REGISTRY: Dict[str, Type[BaseStrategy]] = {}

def register(name: str):
    """装饰器：注册策略类到全局表"""
    def wrapper(cls: Type[BaseStrategy]) -> Type[BaseStrategy]:
        _REGISTRY[name] = cls
        return cls
    return wrapper

def load_strategies(config: List[Dict]) -> List[BaseStrategy]:
    """根据配置列表实例化策略"""
    strategies = []
    for cfg in config:
        name = cfg.get("name")
        if name not in _REGISTRY:
            print(f"⚠️ 未知策略: {name}，可用: {list(_REGISTRY.keys())}")
            continue
        params = cfg.get("params", {})
        strategies.append(_REGISTRY[name](**params))
    return strategies

def list_available() -> List[str]:
    """返回已注册策略名称列表"""
    return list(_REGISTRY.keys())
