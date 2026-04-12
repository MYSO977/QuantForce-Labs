"""ExecutionRouter v1.4+: 支持 Strategy Artifact 热加载"""
import logging, yaml
from pathlib import Path
from typing import List, Dict, Optional

from .contracts import Signal, Order, RiskResult
from .base_strategy import BaseStrategy
from .strategy_loader import StrategyLoader  # 新增导入

log = logging.getLogger("QuantForce.Router")

class ExecutionRouter:
    def __init__(self, config_path: str = "config/strategies.yaml"):
        self.config_path = Path(config_path)
        self._strategies: Dict[str, BaseStrategy] = {}
        self._priority_queue: List[BaseStrategy] = []
        self.loader = StrategyLoader(self)  # 新增: 绑定 Loader
        self.reload_config()
    
    def reload_config(self):
        """热重载配置 + 自动加载 Strategy Artifacts"""
        # 1. 加载传统 YAML 配置 (向后兼容)
        if self.config_path.exists():
            with open(self.config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            # ... 原有逻辑保持不变 ...
        
        # 2. 加载 Strategy Artifacts (新增)
        self.loader.load_all()
        self._rebuild_priority_queue()
        log.info(f"✅ Router 重载完成: {len(self._strategies)} 个策略就绪")
    
    def register_strategy(self, strategy: BaseStrategy):
        """注册单个策略 (被 StrategyLoader 调用)"""
        self._strategies[strategy.strategy_id] = strategy
        log.debug(f"📦 注册策略: {strategy.strategy_id} (priority={getattr(strategy, 'priority', 50)})")
    
    def unregister_strategy(self, strategy_id: str):
        """注销策略 (用于热重载)"""
        if strategy_id in self._strategies:
            del self._strategies[strategy_id]
            log.info(f"🗑️ 注销策略: {strategy_id}")
    
    def _rebuild_priority_queue(self):
        """按 priority 降序重排策略执行顺序"""
        self._priority_queue = sorted(
            self._strategies.values(),
            key=lambda s: getattr(s, "priority", 50),
            reverse=True
        )
    
    def route_signals(self, bar: dict, context: dict) -> List[Signal]:
        """执行策略路由: 按优先级依次调用 generate_signal"""
        all_signals = []
        for strategy in self._priority_queue:
            try:
                # 影子模式策略: 记录信号但不加入执行队列 (由上层控制)
                if getattr(strategy, "shadow_mode", False):
                    sig = strategy.generate_signal(context.get("spec"), bar, context)
                    if sig:
                        # 记录到 ShadowCompareEngine (实际应注入)
                        log.debug(f"🔵 SHADOW: {strategy.strategy_id} → {sig.action.value} {sig.symbol}")
                    continue
                
                signals = strategy.on_bar(context.get("instrument", "UNKNOWN"), bar, context)
                all_signals.extend(signals)
            except Exception as e:
                log.error(f"❌ 策略 {strategy.strategy_id} 执行错误: {e}")
        return all_signals
    
    def execute(self, signal: Signal, risk_engine) -> Optional[Order]:
        """信号→订单转换 + 风控校验"""
        # 原有逻辑保持不变...
        if risk_engine.pre_trade_check(signal).approved:
            return Order(symbol=signal.symbol, action=signal.action, qty=1.0, meta=signal.meta)
        return None
