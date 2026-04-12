# 🚀 QuantForce Labs v2 - 5 分钟快速开始

## 前置要求
- Python 3.10+
- Interactive Brokers TWS/Gateway（纸面交易模式，端口 7497）
- PostgreSQL（可选，用于状态持久化）

## 一键启动（模拟模式）
```bash
git clone https://github.com/MYSO977/QuantForce-Labs
cd QuantForce-Labs
pip install -r requirements.txt
PYTHONPATH="$(pwd)" python3 prod_main.py
```
