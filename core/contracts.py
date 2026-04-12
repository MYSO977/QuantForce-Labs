from dataclasses import dataclass, field
from typing import Any
from enum import Enum

class Action(str, Enum):
    BUY = "BUY"; SELL = "SELL"; FLAT = "FLAT"

@dataclass(frozen=True)
class Signal:
    symbol: str; action: Action; strength: float = 0.5
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Order:
    symbol: str; action: Action; qty: float
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class RiskResult:
    approved: bool; reason: str = "OK"
