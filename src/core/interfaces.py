"""
interfaces.py — QuantForce Labs 系统宪法
Bar / Signal / Order / Strategy 标准接口定义
文档第二章 2.2
唯一不改的文件，所有模块依赖此接口。
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Bar:
    """行情数据单元"""
    symbol: str
    timestamp: datetime
    asset_type: str          # stock / etf / fut / opt

    open: float
    high: float
    low: float
    close: float

    volume: float
    vwap: float
    rvol: float              # 相对成交量 (relative volume)
    dollar_volume: float     # 用于 Russell3000 动态排名
    atr: float = 0.0         # ATR（14日）
    macd: float = 0.0        # MACD line
    ema9: float = 0.0        # EMA9
    day_open: float = 0.0    # 当日开盘价


@dataclass
class Signal:
    """标准信号工单"""
    symbol: str
    direction: str           # BUY / SELL / FLAT
    confidence: float        # 0.0 ~ 1.0
    strategy_id: str         # 插件唯一ID: tech_v2 / news_v4
    asset_type: str          # stock / etf / fut / opt
    reason: str
    timestamp: datetime
    meta: dict = field(default_factory=dict)   # 扩展字段，不破坏接口
    is_primary: bool = True  # True=主策略 False=次要条件
    signal_id: Optional[str] = None
    score: float = 0.0       # LLM评分 (0~10)
    rvol: float = 0.0        # 信号时刻RVOL
    price: float = 0.0       # 信号时刻价格
    atr: float = 0.0         # 信号时刻ATR


@dataclass
class Order:
    """执行订单"""
    signal: Signal           # 完整追溯链
    qty: int                 # 风控计算得出
    order_type: str          # MKT / LMT / BRACKET / TWAP
    limit_price: float = 0.0
    stop_price: float = 0.0
    tif: str = "DAY"         # DAY / GTC / IOC
    account: str = ""


class Strategy(ABC):
    """策略插件基类"""
    strategy_id: str         # 全局唯一
    asset_types: list        # 支持品种: ['stock', 'etf', ...]
    is_primary: bool = True  # 主策略 or 次要条件
    priority: int = 0        # 评分权重

    @abstractmethod
    def on_bar(self, bar: Bar) -> Optional[Signal]:
        """
        每根Bar调用一次。
        返回 Signal 表示有信号，返回 None 表示无信号。
        """
        pass

    def on_start(self) -> None:
        """策略启动时调用（可选重写）"""
        pass

    def on_stop(self) -> None:
        """策略停止时调用（可选重写）"""
        pass