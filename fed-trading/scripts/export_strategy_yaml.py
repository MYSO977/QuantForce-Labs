#!/usr/bin/env python3
"""导出联邦训练成果为标准 Strategy Artifact YAML"""
import yaml, uuid, argparse, sys
from datetime import datetime
from pathlib import Path

def export_strategy_artifact(
    strategy_id: str,
    fedavg_model_path: str,
    backtest_results: dict,
    parameters: dict,
    nodes: list = None,
    output_dir: str = "config/strategies"
):
    nodes = nodes or ["node_10", "node_11", "node_12"]
    
    artifact = {
        "strategy_id": strategy_id,
        "version": datetime.now().strftime("%Y.%m.%d"),
        "source": {
            "model": f"lora_fedavg_{Path(fedavg_model_path).name}",
            "nodes": nodes,
            "trace_id": str(uuid.uuid4()),
            "exported_at": datetime.now().isoformat()
        },
        "performance": {
            "sharpe": round(backtest_results.get("sharpe", 0), 2),
            "max_drawdown": round(backtest_results.get("max_dd", 0), 1),
            "win_rate": round(backtest_results.get("win_rate", 0), 2),
            "total_trades": backtest_results.get("count", 0)
        },
        "regime": {
            "best": backtest_results.get("best_regime", "unknown"),
            "worst": backtest_results.get("worst_regime", "unknown")
        },
        "parameters": parameters,
        "risk": {
            "position_size": "dynamic",
            "atr_multiplier": 2.0,
            "max_exposure_pct": 0.15
        },
        # 安全开关：默认影子模式 + 人工审批
        "enabled": False,
        "shadow_mode": True,
        "manual_approval": True,
        "shadow_compare_days": 5
    }

    output_path = Path(output_dir) / f"{strategy_id}.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(artifact, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    print(f"✅ Strategy Artifact 已生成: {output_path}")
    return output_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True, help="策略唯一标识，如 fed_momentum_v3")
    parser.add_argument("--model", required=True, help="FedAvg 模型路径")
    parser.add_argument("--results", type=str, help="回测结果 JSON 字符串")
    parser.add_argument("--params", type=str, help="策略参数 JSON 字符串")
    parser.add_argument("--output", default="config/strategies")
    args = parser.parse_args()
    
    import json
    results = json.loads(args.results) if args.results else {}
    params = json.loads(args.params) if args.params else {}
    
    export_strategy_artifact(args.id, args.model, results, params, output_dir=args.output)
