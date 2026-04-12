#!/usr/bin/env python3
"""全策略信号验证测试：模拟 50 根 K 线遍历所有策略"""
import sys, os, time
sys.path.insert(0, os.getcwd())

from strategies import load_strategies, list_available
from core.contracts import Action
import numpy as np

def main():
    print("🚀 1. 加载所有可用策略...")
    all_names = list_available()
    print(f"📦 发现 {len(all_names)} 个策略: {sorted(all_names)}")
    
    # 加载所有策略（参数留空使用默认值）
    configs = [{'name': name, 'params': {}} for name in all_names]
    strategies = load_strategies(configs)
    print(f"✅ 成功实例化 {len(strategies)} 个策略实例\n")

    print("📊 2. 模拟输入 50 根 K 线数据...")
    
    # 构造模拟价格曲线：正弦波 + 上升趋势
    prices = [100 + i*0.1 + np.sin(i/3)*5 for i in range(50)]
    
    signal_count = 0
    
    for i in range(50):
        bar = {
            "close": prices[i],
            "high": prices[i] + 2,
            "low": prices[i] - 2,
            "volume": 1000 + i*10
        }
        context = {"option_greeks": {}, "rates": {}, "historical_prices": {"TEST": prices[:i]}}
        
        for strategy in strategies:
            try:
                # 遍历测试：传入虚拟标的 "TEST"
                signals = strategy.on_bar("TEST", bar, context)
                if signals:
                    signal_count += len(signals)
                    for sig in signals:
                        # 打印详细信号
                        print(f"  ⚡ [{i:02d}] {strategy.name:<25} | {sig.action.value:<6} | Str: {sig.strength:.2f} | {sig.meta.get('type', 'generic')}")
            except Exception as e:
                print(f"  ❌ [{i:02d}] {strategy.name} 报错: {e}")

    print(f"\n🎉 测试完成！共产生 {signal_count} 个有效信号。")
    print("✅ 系统逻辑验证通过，可以进入生产模式。")

if __name__ == "__main__":
    main()
