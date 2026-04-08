#!/usr/bin/env python3
"""
tech_scanner.py — 技术指标扫描器
三台机器通用，通过 CONFIG 区分部署参数
"""
import time, logging, threading, random
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo
import urllib.request

import requests
import pandas as pd
import yfinance as yf

# ─── CONFIG（部署时按节点修改）───────────────────────────────
import socket as _socket
_HOSTNAME = _socket.gethostname()
_NODE_MAP = {"dell-trading": "executor", "compute": "compute", "vision": "vision"}
NODE_NAME     = _NODE_MAP.get(_HOSTNAME, _HOSTNAME)
MAX_WORKERS   = 10
SIGNAL_URL    = "http://192.168.0.18:5800/signal"
SCAN_INTERVAL = 300
COOLDOWN_MIN  = 60
PRICE_MIN     = 5.0
PRICE_MAX     = 800.0
MIN_AVG_VOL   = 300_000
TICKER_SOURCE = f"/home/heng/tickers_{NODE_NAME}.txt"
# ─────────────────────────────────────────────────────────────

ET = ZoneInfo("America/New_York")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(f"/tmp/tech_scanner_{NODE_NAME}.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

_cooldown: dict[str, datetime] = {}
_cooldown_lock = threading.Lock()


def get_tickers(source: str) -> list[str]:
    urls = {
        "sp500":      "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
        "nasdaq100":  "https://raw.githubusercontent.com/datasets/nasdaq-listings/main/data/nasdaq-listed.csv",
        "russell1000":"https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
    }
    try:
        if source.startswith("/"):
            with open(source) as f:
                tickers = [l.strip() for l in f if l.strip()]
            log.info(f"股票池加载: {len(tickers)} 只 ({source})")
            return tickers
        url = urls.get(source, urls["sp500"])
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=10).read().decode()
        lines = data.strip().split("\n")[1:]
        tickers = [l.split(",")[0].replace(".", "-") for l in lines if l.strip()]
        log.info(f"股票池加载: {len(tickers)} 只 ({source})")
        return tickers
    except Exception as e:
        log.error(f"股票池加载失败: {e}")
        return []


def is_market_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    c = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return o <= now <= c


def analyze_ticker(ticker: str) -> dict | None:
    try:
        time.sleep(random.uniform(0.1, 0.4))
        tk = yf.Ticker(ticker)

        df1 = tk.history(period="1d", interval="1m")
        if df1.empty or len(df1) < 10:
            return None

        df5 = tk.history(period="5d", interval="5m")
        if df5.empty or len(df5) < 30:
            return None

        current_price = float(df1["Close"].iloc[-1])
        open_price    = float(df1["Open"].iloc[0])

        if not (PRICE_MIN <= current_price <= PRICE_MAX):
            return None

        # RVOL
        now_et  = datetime.now(ET)
        elapsed = max((now_et.hour * 60 + now_et.minute) - (9 * 60 + 30), 1)
        cum_vol = float(df1["Volume"].sum())
        df5d    = tk.history(period="5d", interval="1d")
        if len(df5d) >= 2:
            avg_daily = float(df5d["Volume"].iloc[:-1].mean())
            avg_now   = avg_daily * (elapsed / 390)
        else:
            avg_now = cum_vol
        rvol = cum_vol / avg_now if avg_now > 0 else 0

        if cum_vol < MIN_AVG_VOL:
            return None

        # VWAP
        df1["tp"]  = (df1["High"] + df1["Low"] + df1["Close"]) / 3
        df1["tpv"] = df1["tp"] * df1["Volume"]
        vwap = float(df1["tpv"].cumsum().iloc[-1] / df1["Volume"].cumsum().iloc[-1])

        # EMA9
        closes5 = df5["Close"]
        ema9    = closes5.ewm(span=9, adjust=False).mean()
        cond_ema9 = float(ema9.iloc[-1]) > float(ema9.iloc[-2])

        # MACD
        ema12     = closes5.ewm(span=12, adjust=False).mean()
        ema26     = closes5.ewm(span=26, adjust=False).mean()
        macd_line = float((ema12 - ema26).iloc[-1])

        # 5条件
        if not all([
            rvol >= 2.0,
            current_price > vwap,
            cond_ema9,
            macd_line > 0,
            current_price > open_price
        ]):
            return None

        return {
            "ticker": ticker,
            "price":  round(current_price, 2),
            "open":   round(open_price, 2),
            "rvol":   round(rvol, 2),
            "vwap":   round(vwap, 2),
            "macd":   round(macd_line, 4),
            "source": f"tech_scanner_{NODE_NAME}",
            "score":  7.5,
            "ts":     datetime.now(ET).isoformat()
        }
    except Exception as e:
        log.debug(f"{ticker} 失败: {e}")
        return None


def check_cooldown(ticker: str) -> bool:
    with _cooldown_lock:
        last = _cooldown.get(ticker)
        if last and (datetime.now(ET) - last) < timedelta(minutes=COOLDOWN_MIN):
            return False
        _cooldown[ticker] = datetime.now(ET)
        return True


def push_signal(sig: dict):
    try:
        r = requests.post(SIGNAL_URL, json=sig, timeout=5)
        log.info(f"✅ {sig['ticker']} RVOL={sig['rvol']} 价格={sig['price']} → {r.status_code}")
    except Exception as e:
        log.error(f"发送失败 {sig['ticker']}: {e}")


def run_scan(tickers: list[str]):
    if not is_market_open():
        log.info("非交易时间，跳过")
        return
    now_et = datetime.now(ET)
    if now_et.hour == 9 and now_et.minute < 35:
        log.info("开盘前5分钟，等待稳定...")
        return
    now_et = datetime.now(ET)
    if now_et.hour == 9 and now_et.minute < 35:
        log.info("开盘前5分钟，等待稳定...")
        return

    log.info(f"扫描 {len(tickers)} 只，{MAX_WORKERS} 线程...")
    t0 = time.time()
    signals = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(analyze_ticker, tk): tk for tk in tickers}
        for fut in as_completed(futures):
            result = fut.result()
            if result and check_cooldown(result["ticker"]):
                signals.append(result)
                push_signal(result)

    elapsed = round(time.time()-t0, 1)
    log.info(f"完成 {elapsed}s，信号 {len(signals)} 个")
    try:
        import socket
        node = NODE_NAME
        requests.post("http://192.168.0.18:5800/scanner/status", json={
            "node": node,
            "total": len(tickers),
            "signals": len(signals),
            "elapsed_s": elapsed,
            "last_scan": datetime.now(ET).isoformat(),
            "updated_at": datetime.now(ET).isoformat(),
        }, timeout=3)
    except Exception:
        pass


def main():
    log.info(f"=== tech_scanner [{NODE_NAME}] 启动 ===")
    tickers = get_tickers(TICKER_SOURCE)
    if not tickers:
        log.error("股票池为空，退出")
        return

    while True:
        try:
            run_scan(tickers)
            if datetime.now(ET).weekday() == 0 and datetime.now(ET).hour < 9:
                tickers = get_tickers(TICKER_SOURCE)
        except Exception as e:
            log.error(f"异常: {e}")
        # 心跳上报
        try:
            requests.post("http://192.168.0.18:5800/scanner/status", json={
                "node": NODE_NAME,
                "total": len(tickers),
                "signals": 0,
                "elapsed_s": 0,
                "updated_at": datetime.now(ET).isoformat(),
                "last_scan": None,
            }, timeout=3)
        except Exception:
            pass
        log.info(f"等待 {SCAN_INTERVAL}s...")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
