import asyncio, logging, os, time, uuid, httpx, psycopg2, zmq, zmq.asyncio
from ib_insync import IB, MarketOrder, Stock, util

logging.basicConfig(level=logging.INFO, format="%(asctime)s [IB_EXECUTOR] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("/home/heng/ib_executor.log")])
log = logging.getLogger(__name__)

IB_HOST      = os.getenv("IB_HOST", "192.168.0.11")
IB_PORT      = int(os.getenv("IB_PORT", "4002"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "11"))
ZMQ_PORT     = int(os.getenv("ZMQ_PORT", "5558"))
DEDUP_TTL    = 300
PHI3_URL     = "http://localhost:11434/api/generate"
PHI3_MODEL   = "phi3:mini"
PHI3_TIMEOUT = 30
PG_DSN = os.getenv("QUANT_PG_DSN","host=192.168.0.18 port=5432 dbname=quantforce user=heng password=quantforce123")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN","")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","")
ANOMALY_REJECT_THRESHOLD = 3
ANOMALY_SLIPPAGE_PCT     = 0.5
_seen_signals = {}
_reject_count = 0

def _is_duplicate(sid):
    now = time.time()
    for k in [k for k,v in _seen_signals.items() if now-v>DEDUP_TTL]: del _seen_signals[k]
    if sid in _seen_signals: return True
    _seen_signals[sid] = now; return False

async def send_telegram(msg):
    if not TELEGRAM_TOKEN: log.warning(f"[TG] 未配置: {msg}"); return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                         json={"chat_id":TELEGRAM_CHAT_ID,"text":msg})
    except Exception as e: log.warning(f"[TG] 失败: {e}")

async def call_phi3(prompt):
    try:
        async with httpx.AsyncClient(timeout=PHI3_TIMEOUT) as c:
            r = await c.post(PHI3_URL, json={"model":PHI3_MODEL,"prompt":prompt,"stream":False})
            return r.json().get("response","").strip()
    except Exception as e: log.warning(f"[PHI3] 失败: {e}"); return f"phi3 error: {e}"

async def phi3_pre_check(signal, qty, order_type, exec_id):
    ticker = signal.get("ticker","?")
    prompt = (f"Trading execution assistant. Evaluate briefly.\n"
              f"Stock:{ticker} Action:{signal.get('action','BUY')} Price:${signal.get('price',0):.2f} "
              f"Qty:{qty} Type:{order_type} Score:{signal.get('score',0)}/10 RVOL:{signal.get('rvol',0):.1f}x\n"
              f"1-2 sentences: reasonable execution? Note slippage or timing risks.")
    result = await call_phi3(prompt)
    log.info(f"[PHI3 PRE] {ticker}: {result}")
    await _update_phi3_note(exec_id, f"[PRE] {result}")
    if any(kw in result.lower() for kw in ["high risk","avoid","dangerous","do not","slippage risk"]):
        await send_telegram(f"⚠️ phi3预警 {ticker}\n{result}")

async def phi3_post_summary(signal, qty, fill_price, order_price, exec_id):
    ticker = signal.get("ticker","?")
    slip = abs(fill_price-order_price)/order_price*100 if order_price>0 else 0
    prompt = (f"Execution summary: {ticker} {signal.get('action','BUY')}\n"
              f"Signal:${order_price:.2f} Fill:${fill_price:.2f} Qty:{qty} Slippage:{slip:.3f}%\n"
              f"Score:{signal.get('score',0)}/10 RVOL:{signal.get('rvol',0):.1f}x\n"
              f"1 sentence execution quality summary.")
    result = await call_phi3(prompt)
    log.info(f"[PHI3 POST] {ticker}: {result}")
    await _append_phi3_note(exec_id, f"[POST] {result}")
    if slip > ANOMALY_SLIPPAGE_PCT:
        await send_telegram(f"⚠️ phi3滑点告警 {ticker}\n滑点{slip:.3f}%>{ANOMALY_SLIPPAGE_PCT}%\n{result}")

async def phi3_anomaly_monitor():
    log.info("[PHI3 ANOMALY] 监控启动")
    while True:
        await asyncio.sleep(60)
        try:
            with open("/home/heng/ib_executor.log") as f: lines = f.readlines()
            recent = "".join(lines[-20:])
            prompt = (f"Monitor IB executor logs:\n{recent}\n"
                      f"Reply OK if normal, or ALERT:<reason> if anomaly (rejections/disconnects/errors).")
            result = await call_phi3(prompt)
            log.info(f"[PHI3 ANOMALY] {result}")
            if result.upper().startswith("ALERT"): await send_telegram(f"🚨 phi3异常\n{result}")
        except Exception as e: log.warning(f"[PHI3 ANOMALY] {e}")

def _pg_write_execution(signal, qty, ib_order_id, order_type):
    try:
        conn = psycopg2.connect(PG_DSN); cur = conn.cursor()
        cur.execute("INSERT INTO executions (ts,symbol,action,qty,price,order_type,ib_order_id,signal_id) VALUES (NOW(),%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (signal.get("ticker"),signal.get("action","BUY"),qty,signal.get("price",0),order_type,ib_order_id,signal.get("signal_id")))
        eid = cur.fetchone()[0]; conn.commit(); cur.close(); conn.close(); return eid
    except Exception as e: log.error(f"[PG] 写失败: {e}"); return -1

async def _update_phi3_note(exec_id, note):
    if exec_id<0: return
    try:
        conn = psycopg2.connect(PG_DSN); cur = conn.cursor()
        cur.execute("UPDATE executions SET phi3_note=%s WHERE id=%s",(note,exec_id))
        conn.commit(); cur.close(); conn.close()
    except Exception as e: log.warning(f"[PG] update失败: {e}")

async def _append_phi3_note(exec_id, note):
    if exec_id<0: return
    try:
        conn = psycopg2.connect(PG_DSN); cur = conn.cursor()
        cur.execute("UPDATE executions SET phi3_note=COALESCE(phi3_note,'')||' | '||%s WHERE id=%s",(note,exec_id))
        conn.commit(); cur.close(); conn.close()
    except Exception as e: log.warning(f"[PG] append失败: {e}")

async def _wait_fill_and_summarize(trade, signal, qty, order_price, exec_id):
    try:
        for _ in range(30):
            await asyncio.sleep(1)
            if trade.orderStatus.status in ("Filled","Submitted"):
                fp = trade.orderStatus.avgFillPrice or order_price
                if fp>0: await phi3_post_summary(signal,qty,fp,order_price,exec_id); return
        log.info(f"[PHI3 POST] {signal.get('ticker')} 30s未成交，跳过")
    except Exception as e: log.warning(f"[PHI3 POST] {e}")

async def process_signal(ib, signal):
    global _reject_count
    ticker=signal.get("ticker"); action=signal.get("action","BUY").upper()
    price=signal.get("price",0); size=signal.get("size"); atr=signal.get("atr",0)
    sid=signal.get("signal_id") or str(uuid.uuid4())
    if not ticker: log.warning(f"无ticker: {signal}"); return
    if _is_duplicate(sid): log.warning(f"重复: {sid} {ticker}"); return
    qty = int(size) if size and int(size)>0 else (max(1,int(1000/price)) if price>0 else 0)
    if not qty: log.warning(f"无法计算股数: {signal}"); return
    contract = Stock(ticker,"SMART","USD"); ib.qualifyContracts(contract)
    order_type="MKT"; trade=None
    try:
        if action=="BUY":
            if atr>0 and price>0:
                order_type="BRACKET"
                sp=round(price-2.0*atr,2); tp=round(price+3.0*atr,2)
                bracket=ib.bracketOrder("BUY",qty,limitPrice=price,takeProfitPrice=tp,stopLossPrice=sp)
                bracket[0]=MarketOrder("BUY",qty); bracket[0].transmit=False
                bracket[1].parentId=bracket[0].orderId; bracket[2].parentId=bracket[0].orderId; bracket[2].transmit=True
                trades=[ib.placeOrder(contract,o) for o in bracket]; await asyncio.sleep(1); trade=trades[0]
                log.info(f"BRACKET BUY {ticker} qty={qty} stop={sp} tp={tp} status={trade.orderStatus.status}")
            else:
                order=MarketOrder("BUY",qty); trade=ib.placeOrder(contract,order)
                await asyncio.sleep(1); log.info(f"MKT BUY {ticker} qty={qty} status={trade.orderStatus.status}")
        elif action=="SELL":
            positions={p.contract.symbol:p for p in ib.positions()}; pos=positions.get(ticker)
            if pos and abs(pos.position)>0:
                sq=int(abs(pos.position)); order=MarketOrder("SELL",sq); trade=ib.placeOrder(contract,order)
                await asyncio.sleep(1); log.info(f"MKT SELL {ticker} qty={sq} status={trade.orderStatus.status}")
            else: log.warning(f"SELL {ticker} 无持仓"); return
        else: log.warning(f"未知action={action}"); return
        _reject_count=0
        eid=_pg_write_execution(signal,qty,trade.order.orderId if trade else -1,order_type)
        asyncio.create_task(phi3_pre_check(signal,qty,order_type,eid))
        if trade: asyncio.create_task(_wait_fill_and_summarize(trade,signal,qty,price,eid))
    except Exception as e:
        log.error(f"下单异常 {ticker}: {e}"); _reject_count+=1
        if _reject_count>=ANOMALY_REJECT_THRESHOLD:
            await send_telegram(f"🚨 连续拒单{_reject_count}次\n{e}"); _reject_count=0

async def main():
    util.startLoop()
    log.info(f"连接 IB Gateway {IB_HOST}:{IB_PORT}")
    ib=IB(); await ib.connectAsync(IB_HOST,IB_PORT,clientId=IB_CLIENT_ID)
    log.info(f"已连接 accounts={ib.managedAccounts()}")
    ctx=zmq.asyncio.Context(); pull=ctx.socket(zmq.PULL)
    pull.bind(f"tcp://*:{ZMQ_PORT}"); log.info(f"ZMQ PULL 监听:{ZMQ_PORT}")
    asyncio.create_task(phi3_anomaly_monitor())
    while True:
        try:
            if not ib.isConnected():
                log.warning("IB断连，重连..."); await ib.connectAsync(IB_HOST,IB_PORT,clientId=IB_CLIENT_ID)
            msg=await pull.recv_json()
            log.info(f"收到: {msg.get('ticker','?')} action={msg.get('action','?')} size={msg.get('size')} price={msg.get('price')} score={msg.get('score')}")
            await process_signal(ib,msg)
        except Exception as e: log.error(f"主循环: {e}"); await asyncio.sleep(1)

if __name__=="__main__": asyncio.run(main())