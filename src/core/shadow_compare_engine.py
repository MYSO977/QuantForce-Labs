"""Shadow Mode 对比引擎：评估新策略是否值得晋升"""
import logging, json
from datetime import datetime, timedelta
from typing import Dict, Optional
from dataclasses import dataclass, asdict

log = logging.getLogger("QuantForce.ShadowCompare")

@dataclass
class CompareReport:
    strategy_id: str
    days_analyzed: int
    recommendation: str  # "ENABLE" | "KEEP_SHADOW" | "DISABLE"
    metrics: Dict
    generated_at: str

class ShadowCompareEngine:
    def __init__(self, db_url: Optional[str] = None):
        # 简化: 实际应接 PostgreSQL，此处用内存字典演示
        self.signal_store: Dict[str, list] = {}
        self.db_url = db_url

    def record_signal(self, strategy_id: str, signal: dict):
        """执行层调用: 记录影子策略信号 (用于后续对比)"""
        self.signal_store.setdefault(strategy_id, []).append({
            **signal, "recorded_at": datetime.now().isoformat()
        })
        # 保留最近 7 天
        cutoff = datetime.now() - timedelta(days=7)
        self.signal_store[strategy_id] = [
            s for s in self.signal_store[strategy_id]
            if datetime.fromisoformat(s["recorded_at"]) > cutoff
        ]

    def compare(self, new_strategy_id: str, baseline_id: str = "momentum", days: int = 5) -> CompareReport:
        """对比新策略与基准策略的样本外表现"""
        cutoff = datetime.now() - timedelta(days=days)
        
        new_signals = [s for s in self.signal_store.get(new_strategy_id, []) 
                      if datetime.fromisoformat(s["recorded_at"]) > cutoff]
        base_signals = [s for s in self.signal_store.get(baseline_id, [])
                       if datetime.fromisoformat(s["recorded_at"]) > cutoff]
        
        if len(new_signals) < 10 or len(base_signals) < 10:
            return CompareReport(
                strategy_id=new_strategy_id,
                days_analyzed=days,
                recommendation="INSUFFICIENT_DATA",
                metrics={"new_count": len(new_signals), "base_count": len(base_signals)},
                generated_at=datetime.now().isoformat()
            )
        
        # 简化指标计算 (实际应接真实成交回报)
        new_strength = sum(s.get("strength", 0) for s in new_signals) / len(new_signals)
        base_strength = sum(s.get("strength", 0) for s in base_signals) / len(base_signals)
        
        # 决策逻辑: 新策略强度提升 >8% 且波动更低 → 推荐启用
        improvement = (new_strength - base_strength) / (base_strength + 1e-6)
        if improvement > 0.08:
            rec = "ENABLE"
        elif improvement < -0.05:
            rec = "DISABLE"
        else:
            rec = "KEEP_SHADOW"
        
        report = CompareReport(
            strategy_id=new_strategy_id,
            days_analyzed=days,
            recommendation=rec,
            metrics={
                "new_avg_strength": round(new_strength, 3),
                "base_avg_strength": round(base_strength, 3),
                "improvement_pct": round(improvement * 100, 1),
                "new_signals": len(new_signals),
                "base_signals": len(base_signals)
            },
            generated_at=datetime.now().isoformat()
        )
        
        log.info(f"📊 Shadow 对比: {new_strategy_id} vs {baseline_id} → {rec} (+{report.metrics['improvement_pct']}%)")
        return report

    def auto_promote(self, report: CompareReport, config_path: str = "config/strategies"):
        """若推荐启用，自动更新 strategy.yaml 的 enabled 字段 (需 manual_approval 确认)"""
        if report.recommendation != "ENABLE":
            return False
        
        import yaml
        from pathlib import Path
        yaml_path = Path(config_path) / f"{report.strategy_id}.yaml"
        if not yaml_path.exists():
            return False
        
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        # 仅当人工审批标记为 True 时才自动启用
        if data.get("manual_approval"):
            data["enabled"] = True
            data["shadow_mode"] = False
            data["promoted_at"] = datetime.now().isoformat()
            data["promotion_report"] = asdict(report)
            
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False)
            
            log.info(f"🚀 自动晋升: {report.strategy_id} → enabled=True")
            return True
        return False
