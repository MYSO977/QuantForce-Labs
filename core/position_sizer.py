from dataclasses import dataclass
@dataclass
class PositionSize: qty: float; risk_amount: float; method: str
def size_order(strength, balance, price, cfg) -> PositionSize:
    return PositionSize(qty=max(1.0, 24.0/(price*0.02)), risk_amount=24.0, method="fixed_risk")
