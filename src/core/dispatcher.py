#!/usr/bin/env python3
"""
QuantForce_Labs - Signal Dispatcher v3.3
Port 5556 PULL — 接收来自 vision(.15) 和 courier(.102) 的信号
四层过滤后推送至 executor
"""
import zmq
import json
import time
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [DISPATCHER] %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

cooldown_tracker = {}

import sqlite3

DB_PATH = '/home/heng/QuantForce_Labs/data/signals.db'

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute('''CREATE TABLE IF NOT EXISTS signals (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ts         TEXT,
        ticker     TEXT,
        result     TEXT,
        score      REAL,
        rvol       REAL,
        price      REAL,
        ema9       REAL,
        vwap       REAL,
        macd       REAL
    )''')
    con.commit()
    con.close()

def log_signal(msg, result):
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute('''INSERT INTO signals
            (ts,ticker,result,score,rvol,price,ema9,vwap,macd)
            VALUES (?,?,?,?,?,?,?,?,?)''', (
            datetime.now(ET).isoformat(),
            msg.get('ticker'), result,
            msg.get('score'), msg.get('rvol'),
            msg.get('price'), msg.get('ema9'),
            msg.get('vwap'),  msg.get('macd'),
        ))
        con.commit()
        con.close()
    except Exception as e:
        log.warning(f"DB write failed: {e}")

import sys
sys.path.insert(0, '/home/heng')
from news_enricher import is_qualified

def L1_news_score(signal):
    score = signal.get('score') or 0
    passed = score >= 7.5
    if not passed:
        log.info(f"L1 FAIL {signal.get('ticker')} score={score} < 7.5")
    return passed

def L2_cooldown(signal):
    ticker = signal.get('ticker')
    now = datetime.now()
    last = cooldown_tracker.get(ticker)
    if last and (now - last) < timedelta(minutes=60):
        log.info(f"L2 FAIL {ticker} cooldown {int((now-last).seconds/60)}min < 60min")
        return False
    cooldown_tracker[ticker] = now
    return True

def L3_rvol_ema(signal):
    rvol = signal.get('rvol') or 0
    passed = rvol >= 2.0
    if not passed:
        log.info(f"L3 FAIL {signal.get('ticker')} rvol={rvol} < 2.0")
    return passed

def L4_price_macd(signal):
    price  = signal.get('price') or 0
    ema9   = signal.get('ema9') or 0
    vwap   = signal.get('vwap') or 0
    open_  = signal.get('open') or 0
    macd   = signal.get('macd') or 0
    passed = price > ema9 > vwap > open_ and macd > 0
    if not passed:
        log.info(f"L4 FAIL {signal.get('ticker')} price={price} ema9={ema9} vwap={vwap} open={open_} macd={macd}")
    return passed


def llm_analyze(msg, signal_id):
    import threading
    def _call():
        try:
            import urllib.request, json as _json
            prompt = (
                f"股票{msg.get('ticker')}触发交易信号。"
                f"新闻评分{msg.get('score')},RVOL={msg.get('rvol')},"
                f"价格{msg.get('price')},MACD={msg.get('macd')}。"
                f"用一句中文简要评价此信号的质量和风险。不超过30字。"
            )
            body = _json.dumps({
                "model": "qwen2.5:0.5b",
                "prompt": prompt,
                "stream": False
            }).encode()
            req = urllib.request.Request(
                "http://192.168.0.143:11434/api/generate",
                data=body,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = _json.loads(r.read())
            note = resp.get("response", "").strip()
            con = sqlite3.connect(DB_PATH)
            con.execute("UPDATE signals SET llm_note=? WHERE id=?", (note, signal_id))
            con.commit()
            con.close()
            log.info(f"LLM note for id={signal_id}: {note}")
        except Exception as e:
            log.warning(f"LLM analyze failed: {e}")
    threading.Thread(target=_call, daemon=True).start()

def run():
    init_db()
    ctx = zmq.Context()
    pull = ctx.socket(zmq.PULL)
    pull.bind("tcp://*:5556")
    log.info("PULL socket bound on port 5556")
    push = ctx.socket(zmq.PUSH)
    push.connect("tcp://192.168.0.11:5557")
    log.info("PUSH socket connected to executor :5557")
    log.info("Dispatcher running, waiting for signals...")
    while True:
        try:
            msg = pull.recv_json()
            ticker = msg.get('ticker', '?')
            log.info(f"Received signal: {ticker}")
            if L1_news_score(msg) and is_qualified(ticker) and L2_cooldown(msg) and L3_rvol_ema(msg) and L4_price_macd(msg):
                log.info(f"✓ PASS {ticker} — forwarding to executor")
                con = sqlite3.connect(DB_PATH)
                cur = con.execute('''INSERT INTO signals
                    (ts,ticker,result,score,rvol,price,ema9,vwap,macd)
                    VALUES (?,?,?,?,?,?,?,?,?)''', (
                    datetime.now(ET).isoformat(), ticker, 'PASS',
                    msg.get('score'), msg.get('rvol'), msg.get('price'),
                    msg.get('ema9'), msg.get('vwap'), msg.get('macd'),
                ))
                con.commit()
                sig_id = cur.lastrowid
                con.close()
                llm_analyze(msg, sig_id)
                dispatched_msg = {**msg, 'dispatched_at': datetime.now().isoformat()}
                push.send_json(dispatched_msg)
                try:
                    from telegram_notify import send
                    score = msg.get('groq_score', '?')
                    rvol  = msg.get('rvol', '?')
                    price = msg.get('price', '?')
                    send(f"🚨 <b>信号触发</b>\n📈 {ticker}\n💯 评分: {score}\n📊 RVOL: {rvol}\n💵 价格: {price}")
                except Exception as te:
                    log.warning(f"Telegram notify failed: {te}")
            else:
                log.info(f"✗ FILTERED {ticker}")
                log_signal(msg, 'FAIL')
        except Exception as e:
            log.error(f"Error: {e}")
            time.sleep(1)

if __name__ == '__main__':
    run()
