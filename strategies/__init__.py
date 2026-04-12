"""策略包入口：自动注册 + 工厂加载"""
from .base_strategy import BaseStrategy
from .factory import register, load_strategies, list_available
from .multi_asset_base import MultiAssetStrategy
from .llm_enhancer import LLMEnhancer

# 导入所有策略模块（触发 @register）
from . import momentum
from .classic import mean_reversion, etf_momentum, futures_donchian, forex_london, options_covered_call

__all__ = ["BaseStrategy", "MultiAssetStrategy", "register", "load_strategies", "list_available", "LLMEnhancer"]
