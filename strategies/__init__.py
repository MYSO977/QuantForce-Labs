"""策略包入口"""
from .factory import register, load_strategies, list_available
from .base_strategy import BaseStrategy
from .multi_asset_base import MultiAssetStrategy
from .llm_enhancer import LLMEnhancer

# 导入策略模块 (触发注册)
from . import momentum
from .classic.mean_reversion import MeanReversionStrategy
from .classic.etf_momentum import ETFMomentumStrategy
from .classic.futures_donchian import FuturesDonchianStrategy
from .classic.forex_london import ForexLondonBreakoutStrategy
from .classic.options_covered_call import CoveredCallStrategy

__all__ = ["BaseStrategy", "MultiAssetStrategy", "register", "load_strategies", "list_available", "LLMEnhancer"]
