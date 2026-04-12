from abc import ABC, abstractmethod
class BaseStrategy(ABC):
    def __init__(self, name: str, params: dict = None): self.name=name; self.params=params or {}
    @abstractmethod
    def generate_signal(self, spec, bar: dict, context: dict): raise NotImplementedError
    def on_bar(self, instrument: str, bar: dict, context: dict) -> list:
        from core.instruments import get_contract
        sig = self.generate_signal(get_contract(instrument), bar, context)
        return [sig] if sig else []
