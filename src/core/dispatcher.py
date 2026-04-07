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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [DISPATCHER] %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

cooldown_tracker = {}

import sys
sys.path.insert(0, '/home/heng')
from news_enricher import is_qualified

def L1_news_score(signal):
    score = signal.get('score', 0)
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
    rvol = signal.get('rvol', 0)
    passed = rvol >= 2.0
    if not passed:
        log.info(f"L3 FAIL {signal.get('ticker')} rvol={rvol} < 2.0")
    return passed

def L4_price_macd(signal):
    price  = signal.get('price', 0)
    ema9   = signal.get('ema9', 0)
    vwap   = signal.get('vwap', 0)
    open_  = signal.get('open', 0)
    macd   = signal.get('macd', 0)
    passed = price > ema9 > vwap > open_ and macd > 0
    if not passed:
        log.info(f"L4 FAIL {signal.get('ticker')} price={price} ema9={ema9} vwap={vwap} open={open_} macd={macd}")
    return passed

def run():
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
        except Exception as e:
            log.error(f"Error: {e}")
            time.sleep(1)

if __name__ == '__main__':
    run()
