from dataclasses import dataclass
from typing import Optional

class AssetClass: 
    STOCK="STOCK"; ETF="ETF"; OPTION="OPTION"; FUTURE="FUTURE"; FOREX="FOREX"

@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    asset_class: str
    multiplier: float = 1.0
    option_type: Optional[str] = None
    strike: Optional[float] = None
    dte: Optional[int] = None

def get_contract(sym):
    return ContractSpec(sym, "STOCK")
