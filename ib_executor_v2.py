#!/usr/bin/env python3
import json, logging, os, signal, time, threading, uuid
from datetime import datetime, timezone
import psycopg2, requests, zmq
from ib_insync import IB, Stock, MarketOrder, LimitOrder

IB_HOST       = "127.0.0.1"
IB_PORT       = 4002
IB_CLIENT_ID  = 20
ZMQ_PULL_PORT = 5558
PG_DSN        = os.environ.get("QUANT_PG_DSN","host=192.168.0.18 port=5432 dbname=quantforce user=heng password=newpassword123")
OLLAMA_URL    = "http://127.0.0.1:11434/api/chat"
PHI3_MODEL    = "phi3:mini"
DEDUP_TTL     = 300

logging.basicConfig(level=logging.INFO, format="%(asctime)s [EXECUTOR] %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

_seen: dict = {}
def is_duplicate(sid):
    now = time.time()
    _seen.update({k:v for k,v in _seen.items() if now-v < DEDUP_TTL})
    if sid in _seen: return True
    _seen[sid] = now
    return False

def _phi3(messages, timeout):
    try:
        r = requests.post(OLLAMA_URL, json={"model":PHI3_MODEL,"messages":messages,"stream":False}, timeout=timeout)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except Exception as e:
        log.warning(f"[phi3] {e}")
        return None

def phi3_pre(sig):
    p = (f"Pre-trade check. Signal: {sig.get('action','BUY')} {sig.get('ticker')} "
         f"@ ${sig.get('price',0):.2f} confidence={sig.get('confidence',0):.2f}. "
         f"Reason: {sig.get('reason','')}. Reply PROCEED or SKIP only.")
    r = _phi3([{"role":"user","content":p}], 10.0)
    if r is None: return True, "timeout"
    ok = "SKIP" not in r.upper()
    log.info(f"[phi3/pre] {sig.get('ticker')} {r[:40]} proceed={ok}")
    return ok, r[:120]

def phi3_post(sig, res):
    p = (f"One sentence (max 80 chars): {res.get('action','BUY')} {res.get('qty')} "
         f"{sig.get('ticker')} @ ${res.get('avg_price',0):.2f} status={res.get('status')} "
         f"latency={res.get('latency_ms')}ms.")
    return _phi3([{"role":"user","content":p}], 10.0) or "timeout"

def phi3_anomaly(lines):
    if not lines: return None
    p = f"Monitor IB executor logs. Reply NORMAL or brief alert:\n" + "\n".join(lines[-30:])
    r = _phi3([{"role":"user","content":p}], 15.0)
    return r[:200] if r and "NORMAL" not in r.upper() else None

INSERT_EXEC = """
INSERT INTO executions (ts,symbol,action,qty,price,order_type,ib_order_id,signal_id,confidence,phi3_note,status)
VALUES (%(ts)s,%(symbol)s,%(action)s,%(qty)s,%(price)s,%(order_type)s,%(ib_order_id)s,%(signal_id)s,%(confidence)s,%(phi3_note)s,%(status)s)
ON CONFLICT DO NOTHING;
"""

def write_exec(conn, row):
    try:
        with conn.cursor() as cur:
            cur.execute(INSERT_EXEC, row)
            if row.get('signal_id') and str(row['signal_id']).isdigit():
                cur.execute("UPDATE signals_final SET status='executed', executed_at=NOW() WHERE id=%s", (int(row['signal_id']),))
        conn.commit()
        log.info(f"[PG] {row['symbol']} {row['action']} qty={row['qty']}")
    except Exception as e:
        log.error(f"[PG] {e}")
        try: conn.rollback()
        except: pass

def place_order(ib, sig):
    ticker = sig.get("ticker","")
    action = sig.get("action","BUY").upper()
    qty    = int(sig.get("size",1))
    price  = float(sig.get("price",0))
    otype  = sig.get("order_type","MKT").upper()
    contract = Stock(ticker,"SMART","USD")
    try: ib.qualifyContracts(contract)
    except Exception as e:
        log.error(f"qualify {ticker}: {e}"); return None
    if action == "SELL":
        pos = {p.contract.symbol:p for p in ib.positions()}.get(ticker)
        if pos and abs(pos.position) > 0: qty = int(abs(pos.position))
        else: log.warning(f"SELL {ticker} 无持仓"); return None
    order = LimitOrder(action, qty, round(price,2)) if otype=="LMT" and price>0 else MarketOrder(action, qty)
    t0 = time.time()
    trade = ib.placeOrder(contract, order)
    ib.sleep(1)
    log.info(f"[ORDER] {ticker} {action} qty={qty} status={trade.orderStatus.status}")
    return {"qty":qty,"avg_price":trade.orderStatus.avgFillPrice or price,
            "status":trade.orderStatus.status,"ib_order_id":trade.order.orderId,
            "latency_ms":int((time.time()-t0)*1000),
            "signal_id":sig.get("signal_id",str(uuid.uuid4())),
            "confidence":float(sig.get("confidence",0)),"order_type":otype,"action":action}

_logbuf, _loglock = [], threading.Lock()
class BufHandler(logging.Handler):
    def emit(self, r):
        with _loglock:
            _logbuf.append(self.format(r))
            if len(_logbuf)>200: _logbuf.pop(0)

def anomaly_thread(stop):
    log.info("[phi3/anomaly] 启动")
    while not stop.wait(300):
        with _loglock: lines = list(_logbuf)
        alert = phi3_anomaly(lines)
        if alert: log.warning(f"[phi3/anomaly] {alert}")

def get_ib():
    ib = IB()
    ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, timeout=15)
    log.info(f"IB就绪 {ib.managedAccounts()}")
    return ib

def get_pg():
    c = psycopg2.connect(PG_DSN)
    log.info("PG就绪")
    return c

def run():
    log.info("=== ib_executor_v2 启动 ===")
    ib = get_ib()
    conn = get_pg()
    ctx = zmq.Context()
    pull = ctx.socket(zmq.PULL)
    pull.bind(f"tcp://*:{ZMQ_PULL_PORT}")
    log.info(f"ZMQ PULL :{ ZMQ_PULL_PORT}")
    h = BufHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(h)
    stop = threading.Event()
    threading.Thread(target=anomaly_thread, args=(stop,), daemon=True).start()
    def _quit(*_):
        stop.set(); pull.close(); ctx.term(); ib.disconnect(); conn.close()
    signal.signal(signal.SIGTERM, _quit)
    signal.signal(signal.SIGINT,  _quit)
    log.info("等待信号...")
    while True:
        try:
            if not ib.isConnected():
                try: ib = get_ib()
                except Exception as e: log.error(e); time.sleep(5); continue
            try: conn.cursor().execute("SELECT 1")
            except:
                try: conn = get_pg()
                except Exception as e: log.error(e)
            try: raw = pull.recv_json(flags=zmq.NOBLOCK)
            except zmq.Again: ib.sleep(0.1); continue
            sid = raw.get("signal_id", str(uuid.uuid4()))
            log.info(f"收到: {raw.get('ticker')} {raw.get('action')} price={raw.get('price')} sid={str(sid)[:8]}")
            if is_duplicate(sid): log.info("重复跳过"); continue
            ok, pre_note = phi3_pre(raw)
            if not ok: log.warning(f"[phi3/pre] SKIP {raw.get('ticker')}"); continue
            res = place_order(ib, raw)
            if res is None: continue
            def _post(s=raw, r=res, n=pre_note):
                summ = phi3_post(s, r)
                write_exec(conn, {"ts":datetime.now(timezone.utc),"symbol":s.get("ticker"),
                    "action":r["action"],"qty":r["qty"],"price":round(r["avg_price"],4),
                    "order_type":r["order_type"],"ib_order_id":str(r["ib_order_id"]),
                    "signal_id":r["signal_id"],"confidence":r["confidence"],
                    "phi3_note":f"[pre:{n[:40]}][post:{summ[:80]}]","status":r["status"]})
            threading.Thread(target=_post, daemon=True).start()
        except zmq.ZMQError as e:
            if e.errno == zmq.ETERM: break
            log.error(f"ZMQ:{e}")
        except Exception as e:
            log.error(f"异常:{e}", exc_info=True); time.sleep(1)
    log.info("=== 退出 ===")

if __name__ == "__main__":
    run()
