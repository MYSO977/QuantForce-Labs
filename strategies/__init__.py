import importlib, pkgutil, logging
from pathlib import Path
from .base import BaseStrategy

log = logging.getLogger(__name__)
_registry: dict = {}

def discover(package_path=None):
    global _registry
    _registry = {}
    pkg_dir = Path(package_path or __file__).parent
    for _, module_name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if module_name.startswith("_") or module_name == "base":
            continue
        try:
            mod = importlib.import_module(f".{module_name}", package=__name__)
            for attr_name in dir(mod):
                obj = getattr(mod, attr_name)
                if isinstance(obj, type) and issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
                    _registry[obj.name] = obj
                    log.info(f"策略注册: {obj.name} v{obj.version}")
        except Exception as e:
            log.warning(f"模块 {module_name} 加载失败: {e}")
    log.info(f"共注册 {len(_registry)} 个策略: {list(_registry.keys())}")
    return _registry

def get(name): return _registry.get(name)
def all_strategies(): return list(_registry.values())
def primary_strategies(): return [s for s in _registry.values() if s().is_primary()]
