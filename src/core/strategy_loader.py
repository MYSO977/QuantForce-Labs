"""Strategy Artifact Loader: 零侵入加载 YAML 策略为 BaseStrategy 插件"""
import yaml, logging, importlib
from pathlib import Path
from typing import Dict, List, Optional

from .base_strategy import BaseStrategy
from .contracts import Signal, Action

log = logging.getLogger("QuantForce.StrategyLoader")

class StrategyLoader:
    def __init__(self, router, strategies_dir: str = "config/strategies"):
        self.router = router
        self.strategies_dir = Path(strategies_dir)
        self._loaded: Dict[str, BaseStrategy] = {}

    def load_all(self, only_enabled: bool = False) -> List[str]:
        """扫描并加载所有 strategy.yaml (支持 shadow_mode)"""
        loaded = []
        for yaml_file in sorted(self.strategies_dir.glob("*.yaml")):
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                
                # 过滤逻辑
                if not data.get("enabled") and not data.get("shadow_mode"):
                    continue
                if only_enabled and not data.get("enabled"):
                    continue
                
                strategy = self._build_strategy_wrapper(data, yaml_file)
                if strategy:
                    self.router.register_strategy(strategy)
                    self._loaded[data["strategy_id"]] = strategy
                    mode = "🟢 LIVE" if data.get("enabled") else "🔵 SHADOW"
                    log.info(f"{mode} 已注册策略: {data['strategy_id']} v{data['version']}")
                    loaded.append(data["strategy_id"])
            except Exception as e:
                log.error(f"❌ 加载失败 {yaml_file}: {e}")
        return loaded

    def _build_strategy_wrapper(self, artifact: dict, source_path: Path) -> Optional[BaseStrategy]:
        """动态创建 BaseStrategy 子类，绑定 artifact 参数"""
        strat_id = artifact["strategy_id"]
        
        class ArtifactStrategy(BaseStrategy):
            strategy_id = strat_id
            version = artifact["version"]
            is_primary = artifact.get("enabled", False)
            priority = 90 if artifact.get("enabled") else 10
            shadow_mode = artifact.get("shadow_mode", True)
            
            def __init__(self):
                super().__init__(name=strat_id, params=artifact.get("parameters", {}))
                self._artifact = artifact
                self._trace_prefix = artifact["source"].get("trace_id", "")[:8]
            
            def generate_signal(self, spec, bar: dict, context: dict) -> Optional[Signal]:
                # 影子模式: 记录信号但不执行 (由 ExecutionRouter 控制)
                # 实际推理逻辑可注入: from fed_trading.inference import predict
                strength = 0.5  # 占位: 实际应调用 LoRA 推理
                if strength < 0.3:
                    return None
                return Signal(
                    symbol=spec.symbol,
                    action=Action.BUY if strength > 0.5 else Action.SELL,
                    strength=strength,
                    meta={
                        "strategy_id": strat_id,
                        "version": self.version,
                        "trace_id": f"{self._trace_prefix}-{spec.symbol}",
                        "shadow": self.shadow_mode,
                        "artifact_params": self._artifact.get("parameters", {})
                    }
                )
        
        return ArtifactStrategy()

    def reload(self, strategy_id: str) -> bool:
        """热重载单个策略 (用于 manual_approval 后)"""
        yaml_path = self.strategies_dir / f"{strategy_id}.yaml"
        if not yaml_path.exists():
            return False
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # 更新 enabled 状态并重新注册
        if data.get("enabled"):
            self.router.unregister_strategy(strategy_id)
            new_strat = self._build_strategy_wrapper(data, yaml_path)
            if new_strat:
                self.router.register_strategy(new_strat)
                self._loaded[strategy_id] = new_strat
                log.info(f"🔄 热重载成功: {strategy_id} → LIVE")
                return True
        return False
