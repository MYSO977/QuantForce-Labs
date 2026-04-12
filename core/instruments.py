from dataclasses import dataclass
class AssetClass: STOCK="STOCK"; ETF="ETF"; OPTION="OPTION"; FUTURE="FUTURE"; FOREX="FOREX"
@dataclass(frozen=True)
class ContractSpec: symbol: str; asset_class: str; multiplier: float = 1.0
def get_contract(sym): return ContractSpec(sym, "STOCK")
