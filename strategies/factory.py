_REGISTRY = {}
def register(name):
    def wrap(cls): _REGISTRY[name]=cls; return cls
    return wrap
def load_strategies(cfg_list):
    from .base_strategy import BaseStrategy
    return [ _REGISTRY[c["name"]](**c.get("params",{})) for c in cfg_list if c["name"] in _REGISTRY ]
def list_available(): return list(_REGISTRY.keys())
