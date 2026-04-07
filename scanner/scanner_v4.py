#!/usr/bin/env python3
"""
QuantForce_Labs — scanner_v4.py
职责：遍历白名单 → 拉新闻(Finnhub) → 插入 llm_tasks(news_clean)
后续由流水线处理：
  .143 qwen  → news_clean
  .11  phi3  → event_extract
  .18  groq  → signal_decision → dispatcher:5556
"""
import os, json, hashlib, sqlite3, time, logging, requests
from datetime import datetime, timedelta

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
DB_PATH         = os.getenv("LLM_DB", os.path.expanduser("~/llm_data/llm_tasks.db"))
WHITELIST_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whitelist.json")
NEWS_HOURS      = 48

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SCANNER] %(message)s")
log = logging.getLogger(__name__)

def get_news_finnhub(ticker, hours=NEWS_HOURS):
    date_from = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d")
    date_to   = datetime.now().strftime("%Y-%m-%d")
    try:
        r = requests.get("https://finnhub.io/api/v1/company-news",
                         params={"symbol": ticker, "from": date_from,
                                 "to": date_to, "token": FINNHUB_API_KEY}, timeout=8)
        r.raise_for_status()
        return r.json()[:8]
    except Exception as e:
        log.warning(ticker + " finnhub failed: " + str(e))
        return []

def enqueue_news_clean(conn, ticker, news, sector, moat):
    """把新闻拼成文本插入 news_clean 任务"""
    if not news:
        return False
    headlines = "\n".join([
        "- " + n.get("headline","") + " (" + str(n.get("datetime",""))[:10] + ")"
        for n in news[:6]
    ])
    input_text = "ticker:" + ticker + "\nsector:" + sector + "\nmoat:" + moat + "\nnews:\n" + headlines
    h = hashlib.sha256(input_text.encode()).hexdigest()

    cur = conn.cursor()
    # 防重复：同一个hash今天已存在就跳过
    cur.execute("""
        SELECT id FROM llm_tasks
        WHERE input_hash=? AND task_type='news_clean'
          AND date(created_at)=date('now')
    """, (h,))
    if cur.fetchone():
        log.info("  " + ticker + ": already queued today, skip")
        return False

    cur.execute("""
        INSERT INTO llm_tasks (task_type, input_hash, input_text, status)
        VALUES ('news_clean', ?, ?, 'pending')
    """, (h, input_text))
    conn.commit()
    log.info("  " + ticker + ": queued " + str(len(news)) + " news items")
    return True

def run_scan():
    if not FINNHUB_API_KEY:
        log.error("FINNHUB_API_KEY not set")
        return

    with open(WHITELIST_PATH) as f:
        wl = json.load(f)
    tickers = wl["tickers"]

    conn = sqlite3.connect(DB_PATH, timeout=20)
    queued = 0

    log.info("Scan start " + datetime.now().strftime("%Y-%m-%d %H:%M") + "  total=" + str(len(tickers)))

    for item in tickers:
        ticker = item["symbol"]
        sector = item.get("sector", "")
        moat   = item.get("moat", "")
        log.info("-- " + ticker + " --")

        news = get_news_finnhub(ticker)
        if not news:
            log.info("  " + ticker + ": no news, skip")
            time.sleep(0.2)
            continue

        ok = enqueue_news_clean(conn, ticker, news, sector, moat)
        if ok:
            queued += 1
        time.sleep(0.2)

    conn.close()
    log.info("Scan complete  queued=" + str(queued) + "/" + str(len(tickers)))
    log.info("Pipeline: .143 qwen -> .11 phi3 -> .18 groq -> dispatcher:5556")

if __name__ == "__main__":
    import time as _time
    log.info("Scheduler started: scan every 30 minutes")
    while True:
        run_scan()
        log.info("Next scan in 30 minutes...")
        _time.sleep(1800)
