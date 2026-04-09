#!/usr/bin/env python3
"""
Universe Builder v2.0
- 母池：Russell3000（iShares IWV CSV）+ S&P500 fallback
- 过滤：价格≥3, 30日均量≥10万, Dollar Volume排名
- 输出：universe_whitelist 表 + tickers_*.txt 文件（兼容）
"""
import yfinance as yf
import pandas as pd
import psycopg2
import json, os, logging, urllib.request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

DB_DSN = "host=192.168.0.18 port=5432 dbname=quantforce user=heng password=quantforce123"
OUTPUT_DIR    = '/home/heng'
UNIVERSE_SIZE = 2000
MIN_PRICE     = 3.0
MIN_AVG_VOL   = 100_000
DV_WINDOW     = 30
MAX_WORKERS   = 20

IWV_CSV_URL = (
    "https://www.ishares.com/us/products/239714/IWV/"
    "1467271812596.ajax?fileType=csv&fileName=IWV_holdings&dataType=fund"
)
SP500_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies"
    "/main/data/constituents.csv"
)

def fetch_iwv_tickers() -> set:
    try:
        req = urllib.request.Request(IWV_CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", errors="ignore")
        lines = raw.split("\n")
        header_idx = next((i for i, l in enumerate(lines) if l.startswith("Ticker,")), None)
        if header_idx is None:
            log.warning("IWV CSV 格式异常，找不到 Ticker 列")
            return set()
        from io import StringIO
        df = pd.read_csv(StringIO("\n".join(lines[header_idx:])), on_bad_lines="skip")
        tickers = (
            df["Ticker"].dropna().astype(str).str.strip()
            .str.replace(".", "-", regex=False)
        )
        tickers = tickers[tickers.str.match(r'^[A-Z]{1,5}(-[A-Z])?$')]
        result = set(tickers.tolist())
        log.info(f"IWV Russell3000: {len(result)} 只")
        return result
    except Exception as e:
        log.error(f"IWV 获取失败: {e}")
        return set()

def fetch_sp500_tickers() -> set:
    try:
        req = urllib.request.Request(SP500_URL, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=15).read().decode()
        lines = data.strip().split("\n")[1:]
        tickers = {l.split(",")[0].replace(".", "-").strip() for l in lines if l.strip()}
        log.info(f"S&P500 fallback: {len(tickers)} 只")
        return tickers
    except Exception as e:
        log.error(f"S&P500 获取失败: {e}")
        return set()

def get_base_universe() -> list:
    tickers = fetch_iwv_tickers()
    if len(tickers) < 500:
        log.warning("IWV 结果不足，启用 S&P500 fallback")
        tickers |= fetch_sp500_tickers()
    for f in ["tickers_vision.txt", "tickers_executor.txt", "tickers_compute.txt"]:
        path = os.path.join(OUTPUT_DIR, f)
        try:
            with open(path) as fp:
                tickers.update(l.strip() for l in fp if l.strip())
        except:
            pass
    log.info(f"母池合计: {len(tickers)} 只")
    return sorted(tickers)

def calc_dollar_volume(ticker: str):
    try:
        df = yf.Ticker(ticker).history(period=f"{DV_WINDOW+5}d", interval="1d")
        if df.empty or len(df) < 10:
            return None
        df = df.tail(DV_WINDOW)
        price = df["Close"].mean()
        if price < MIN_PRICE:
            return None
        avg_vol = df["Volume"].mean()
        if avg_vol < MIN_AVG_VOL:
            return None
        avg_dv = (df["Close"] * df["Volume"]).mean()
        market_cap = None
        sector = None
        try:
            market_cap = getattr(yf.Ticker(ticker).fast_info, "market_cap", None)
        except:
            pass
        return {
            "ticker": ticker, "avg_dv": avg_dv,
            "price": round(price, 2), "avg_vol": int(avg_vol),
            "sector": sector, "market_cap": market_cap,
        }
    except:
        return None

def write_to_db(ranked: list):
    conn = psycopg2.connect(DB_DSN)
    cur  = conn.cursor()
    now  = datetime.utcnow()
    upsert_sql = """
        INSERT INTO universe_whitelist
            (symbol, dollar_volume_rank, sector, market_cap, avg_dollar_volume, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol) DO UPDATE SET
            dollar_volume_rank = EXCLUDED.dollar_volume_rank,
            sector             = EXCLUDED.sector,
            market_cap         = EXCLUDED.market_cap,
            avg_dollar_volume  = EXCLUDED.avg_dollar_volume,
            updated_at         = EXCLUDED.updated_at
    """
    rows = [
        (r["ticker"], rank+1, r["sector"], float(r["market_cap"]) if r["market_cap"] else None, float(r["avg_dv"]), now)
        for rank, r in enumerate(ranked)
    ]
    cur.executemany(upsert_sql, rows)
    new_symbols = [r["ticker"] for r in ranked]
    cur.execute("DELETE FROM universe_whitelist WHERE symbol != ALL(%s)", (new_symbols,))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    log.info(f"DB 写入: {len(rows)} 条 UPSERT, {deleted} 条旧记录清除")

def write_ticker_files(tickers: list):
    vision   = tickers[0::3]
    executor = tickers[1::3]
    compute  = tickers[2::3]
    for name, data in [("vision", vision), ("executor", executor), ("compute", compute)]:
        path = os.path.join(OUTPUT_DIR, f"tickers_{name}.txt")
        with open(path, "w") as f:
            f.write("\n".join(data))
        log.info(f"{name}: {len(data)} 只 → {path}")

def build_universe():
    log.info("=== Universe Builder v2.0 启动 ===")
    base = get_base_universe()
    log.info(f"开始计算 {len(base)} 只股票的 Dollar Volume ...")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(calc_dollar_volume, t): t for t in base}
        done = 0
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            if r:
                results.append(r)
            if done % 100 == 0:
                log.info(f"进度: {done}/{len(base)}, 有效: {len(results)}")
    results.sort(key=lambda x: x["avg_dv"], reverse=True)
    top = results[:UNIVERSE_SIZE]
    log.info(f"筛选完成: {len(top)} 只入池")
    write_to_db(top)
    tickers = [r["ticker"] for r in top]
    write_ticker_files(tickers)
    meta = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "size": len(top),
        "method": f"{DV_WINDOW}d_avg_dollar_volume",
        "source": "Russell3000(IWV)+SP500_fallback",
        "min_price": MIN_PRICE,
        "min_avg_vol": MIN_AVG_VOL,
        "min_dv_threshold": round(top[-1]["avg_dv"]) if top else 0,
        "generated_at": datetime.now().isoformat(),
    }
    with open(os.path.join(OUTPUT_DIR, "universe_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    log.info(f"=== 完成 size={len(top)} ===")
    return meta

if __name__ == "__main__":
    build_universe()
