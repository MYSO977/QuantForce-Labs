"""策略包入口：自动注册 + 工厂加载"""
from .base_strategy import BaseStrategy
from .factory import register, load_strategies, list_available
from .multi_asset_base import MultiAssetStrategy
from .llm_enhancer import LLMEnhancer

# 自动导入所有策略模块（触发 @register 装饰器）
from . import momentum
from . import etf_momentum, future_curve, forex_carry, option_vol, cross_asset_hedge
from .classic import mean_reversion, pairs_trading, stat_arb, multi_factor, trend_following, event_driven, market_neutral
from . import options_classic
from . import etf_fx_future_classics

__all__ = [
    "BaseStrategy", "MultiAssetStrategy", 
    "register", "load_strategies", "list_available",
    "LLMEnhancer"
]
