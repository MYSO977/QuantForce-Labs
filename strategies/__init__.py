"""策略包入口：自动注册 + 工厂加载"""
from .base_strategy import BaseStrategy
from .factory import register, load_strategies, list_available
from .multi_asset_base import MultiAssetStrategy
from .llm_enhancer import LLMEnhancer

# 显式导入核心策略以触发注册
from . import momentum
# from . import options_classic  # 如需其他策略可在此添加

__all__ = [
    "BaseStrategy", "MultiAssetStrategy", 
    "register", "load_strategies", "list_available",
    "LLMEnhancer"
]
