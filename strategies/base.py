#!/usr/bin/env python3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import pandas as pd

@dataclass
class StrategyResult:
    ticker:    str
    price:     float
    score:     float
    direction: str = "LONG"
    signal_type: str = "tech"
    rvol:      Optional[float] = None
    vwap:      Optional[float] = None
    macd:      Optional[float] = None
    atr:       Optional[float] = None
    meta:      dict = field(default_factory=dict)
    ts:        str  = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_signal(self, source: str) -> dict:
        return {
            "ticker": self.ticker, "price": self.price, "score": self.score,
            "direction": self.direction, "signal_type": self.signal_type,
            "rvol": self.rvol, "vwap": self.vwap, "macd": self.macd,
            "atr": self.atr, "source": source, "ts": self.ts, **self.meta,
        }

class BaseStrategy(ABC):
    name:        str   = "base"
    version:     str   = "1.0"
    signal_type: str   = "tech"
    min_score:   float = 7.5

    def __init__(self, config: dict = None):
        self.config = config or {}

    @abstractmethod
    def analyze(self, ticker, df1m, df5m, df1d) -> Optional[StrategyResult]: ...

    def is_primary(self) -> bool:
        return True

    def __repr__(self):
        return f"<Strategy {self.name} v{self.version}>"
