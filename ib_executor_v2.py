import zmq
import logging
import time
import os
import uuid
import json
from ib_insync import IB, MarketOrder, StopOrder, Stock, BracketOrder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [IB_EXECUTOR] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/home/heng/ib_executor.log")
    ]
)
log = logging.getLogger(__name__)

IB_HOST        = os.getenv("IB_HOST", "192.168.0.18")
IB_PORT        = int(os.getenv("IB_PORT", "4002"))
IB_CLIENT_ID   = int(os.getenv("IB_CLIENT_ID", "2"))
ZMQ_PORT       = 5557
DEDUP_TTL      = 300   # 5分钟内相同signal_id视为重复

# 幂等缓存: signal_id -> timestamp
_seen_signals = {}

def _is_duplicate(signal_id):
    now = time.time()
    # 清理过期记录
    expired = [k for k, v in _seen_signals.items() if now - v > DEDUP_TTL]
    for k in expired:
        del _seen_signals[k]
    if signal_id in _seen_signals:
        return True
    _seen_signals[signal_id] = now
    return False

def get_ib():
    ib = IB()
    ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)
    return ib

def place_order(ib, signal):
    ticker = signal.get("ticker")
    action = signal.get("action", "BUY").upper()
    price  = signal.get("price", 0)
    size   = signal.get("size")   # risk_gate 算出的股数
    atr    = signal.get("atr", 0)

    if not ticker:
        log.warning(f"无 ticker，跳过: {signal}")
        return

    # 幂等校验
    signal_id = signal.get("signal_id") or str(uuid.uuid4())
    if _is_duplicate(signal_id):
        log.warning(f"重复信号忽略: {signal_id} {ticker}")
        return

    contract = Stock(ticker, "SMART", "USD")
    ib.qualifyContracts(contract)

    # 股数：优先用 risk_gate 算出的 size，fallback 到固定1000USD
    if size and int(size) > 0:
        qty = int(size)
    elif price > 0:
        qty = max(1, int(1000 / price))
    else:
        log.warning(f"无法计算股数: {signal}")
        return

    if action == "BUY":
        # 挂 Bracket Order：主单 + 止损单
        if atr > 0 and price > 0:
            stop_price = round(price - 2.0 * atr, 2)
            bracket = ib.bracketOrder(
                "BUY", qty,
                limitPrice=None,       # 市价入场
                takeProfitPrice=round(price + 3.0 * atr, 2),
                stopLossPrice=stop_price,
            )
            for o in bracket:
                o.account = os.getenv("IB_ACCOUNT", "")
            # 主单改为市价单
            bracket[0] = MarketOrder("BUY", qty)
            bracket[0].transmit = False
            bracket[1].parentId = bracket[0].orderId
            bracket[2].parentId = bracket[0].orderId
            bracket[2].transmit = True

            trades = [ib.placeOrder(contract, o) for o in bracket]
            ib.sleep(1)
            trade = trades[0]
            log.info(
                f"BRACKET BUY {ticker} qty={qty} stop={stop_price} "
                f"tp={round(price+3.0*atr,2)} status={trade.orderStatus.status}"
            )
        else:
            # 无ATR，只下市价单
            order = MarketOrder("BUY", qty)
            trade = ib.placeOrder(contract, order)
            ib.sleep(1)
            log.info(f"MARKET BUY {ticker} qty={qty} status={trade.orderStatus.status}")

    elif action == "SELL":
        # 平仓：查当前持仓
        positions = {p.contract.symbol: p for p in ib.positions()}
        pos = positions.get(ticker)
        if pos and abs(pos.position) > 0:
            sell_qty = int(abs(pos.position))
            order = MarketOrder("SELL", sell_qty)
            trade = ib.placeOrder(contract, order)
            ib.sleep(1)
            log.info(f"MARKET SELL {ticker} qty={sell_qty} status={trade.orderStatus.status}")
        else:
            log.warning(f"SELL {ticker} 但无持仓，跳过")
    else:
        log.warning(f"未知 action={action}，跳过")

def run():
    log.info(f"连接 IB Gateway {IB_HOST}:{IB_PORT}")
    ib = get_ib()
    accounts = ib.managedAccounts()
    log.info(f"已连接 accounts={accounts}")

    ctx  = zmq.Context()
    pull = ctx.socket(zmq.PULL)
    pull.bind(f"tcp://*:{ZMQ_PORT}")
    log.info(f"PULL 监听端口 {ZMQ_PORT}，等待信号...")

    while True:
        try:
            if not ib.isConnected():
                log.warning("IB 断连，重连中...")
                ib = get_ib()

            msg    = pull.recv_json()
            ticker = msg.get("ticker", "?")
            action = msg.get("action", "?")
            log.info(
                f"收到信号: {ticker} action={action} "
                f"size={msg.get('size')} price={msg.get('price')} "
                f"score={msg.get('score')}"
            )
            place_order(ib, msg)

        except Exception as e:
            log.error(f"异常: {e}")
            time.sleep(1)

if __name__ == "__main__":
    run()
