#!/usr/bin/env python3
"""
Universe Builder v1.0
每周日凌晨自动运行，生成流动性驱动的2000只股票池
"""
import yfinance as yf
import pandas as pd
import json, os, sys, logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

OUTPUT_DIR   = '/home/heng'
UNIVERSE_SIZE = 2000
MIN_PRICE    = 3.0
MIN_AVG_VOL  = 100_000
DV_WINDOW    = 30  # 天
MAX_WORKERS  = 20

def get_base_universe():
    """获取母池：S&P500 + Russell2000"""
    import urllib.request
    tickers = set()

    sources = {
        "SP500": "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
    }

    for name, url in sources.items():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=15).read().decode()
            lines = data.strip().split('\n')[1:]
            batch = [l.split(',')[0].replace('.', '-').strip() for l in lines if l.strip()]
            tickers.update(batch)
            log.info(f"{name}: {len(batch)} 只")
        except Exception as e:
            log.error(f"{name} 获取失败: {e}")

    # 补充现有池
    for f in ['tickers_vision.txt', 'tickers_executor.txt', 'tickers_compute.txt']:
        path = os.path.join(OUTPUT_DIR, f)
        try:
            with open(path) as fp:
                tickers.update(l.strip() for l in fp if l.strip())
        except: pass

    log.info(f"母池合计: {len(tickers)} 只")
    return sorted(tickers)

def calc_dollar_volume(ticker):
    """计算单只股票30日平均Dollar Volume"""
    try:
        df = yf.Ticker(ticker).history(period=f"{DV_WINDOW+5}d", interval="1d")
        if df.empty or len(df) < 10:
            return None
        df = df.tail(DV_WINDOW)
        price = df['Close'].mean()
        if price < MIN_PRICE:
            return None
        avg_vol = df['Volume'].mean()
        if avg_vol < MIN_AVG_VOL:
            return None
        avg_dv = (df['Close'] * df['Volume']).mean()
        return {'ticker': ticker, 'avg_dv': avg_dv, 'price': round(price, 2), 'avg_vol': int(avg_vol)}
    except:
        return None

def build_universe():
    log.info("=== Universe Builder 启动 ===")
    base = get_base_universe()
    log.info(f"开始计算 {len(base)} 只股票的 Dollar Volume...")

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

    # 按Dollar Volume排序取前2000
    results.sort(key=lambda x: x['avg_dv'], reverse=True)
    top = results[:UNIVERSE_SIZE]

    tickers = [r['ticker'] for r in top]
    min_dv = top[-1]['avg_dv'] if top else 0

    # 交错切分 vision/executor/compute
    vision   = tickers[0::3]
    executor = tickers[1::3]
    compute  = tickers[2::3]

    # 写文件
    for name, data in [('vision', vision), ('executor', executor), ('compute', compute)]:
        path = os.path.join(OUTPUT_DIR, f'tickers_{name}.txt')
        with open(path, 'w') as f:
            f.write('\n'.join(data))
        log.info(f"{name}: {len(data)} 只 → {path}")

    # 写元数据
    meta = {
        "date": datetime.now().strftime('%Y-%m-%d'),
        "size": len(tickers),
        "method": f"{DV_WINDOW}d_avg_dollar_volume",
        "source": "SP500+existing",
        "min_price": MIN_PRICE,
        "min_avg_vol": MIN_AVG_VOL,
        "min_dv_threshold": round(min_dv),
        "split": {"vision": len(vision), "executor": len(executor), "compute": len(compute)},
        "generated_at": datetime.now().isoformat()
    }
    meta_path = os.path.join(OUTPUT_DIR, 'universe_meta.json')
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
    log.info(f"元数据 → {meta_path}")
    log.info(f"完成！Universe size={len(tickers)}, 最低DV={min_dv:,.0f}")
    return meta

if __name__ == '__main__':
    build_universe()
