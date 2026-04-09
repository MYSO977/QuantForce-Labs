#!/usr/bin/env python3
import hashlib,json,os,re,time,uuid
from datetime import datetime,timedelta
import feedparser,psycopg2,requests

FINNHUB_API_KEY=os.getenv("FINNHUB_API_KEY","")
GROQ_API_KEY=os.getenv("GROQ_API_KEY","")
PG_DSN=os.getenv("QUANT_PG_DSN","host=192.168.0.18 port=5432 dbname=quantforce user=heng password=quantforce123")
POLL_SEC=300;SCORE_THRESH=7.5;EXPIRE_HOURS=2;TECH_WINDOW_MIN=60

DEFAULT_WHITELIST=["AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSM","ASML","ADBE","CRM","ORCL","AMD","INTC","QCOM","AVGO","TXN","NOW","SNOW","PLTR","NET","CRWD","DDOG","V","MA","JPM","BAC","GS","MS","BLK","SPGI","AXP","UNH","LLY","JNJ","ABBV","MRK","PFE","TMO","ISRG","REGN","VRTX","COST","WMT","HD","MCD","SBUX","NKE","TSLA","XOM","CVX","NEE","UNP","HON","RTX","LMT","CAT","NFLX","DIS","PG","KO","PEP"]

def load_whitelist():
    try:
        path=os.path.expanduser("~/quant/vision/whitelist.json")
        if os.path.exists(path):
            with open(path) as f:data=json.load(f)
            return [t["symbol"] for t in data.get("tickers",[])]
    except:pass
    return DEFAULT_WHITELIST

def has_tech_signal(conn,ticker):
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM signals_raw WHERE symbol=%s AND signal_type='tech' AND status='pending' AND created_at>NOW()-INTERVAL %s LIMIT 1",(ticker,f"{TECH_WINDOW_MIN} minutes"))
            return cur.fetchone() is not None
    except Exception as e:
        print(f"has_tech_signal error: {e}");return False

def get_score(text):
    if not GROQ_API_KEY:return 5.0
    try:
        r=requests.post("https://api.groq.com/openai/v1/chat/completions",headers={"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"},json={"model":"llama-3.1-8b-instant","messages":[{"role":"system","content":"Score this financial news 0-10 for stock market impact. Output only a number."},{"role":"user","content":text[:300]}],"max_tokens":10,"temperature":0.1},timeout=8)
        j=r.json()
        if r.status_code!=200 or "choices" not in j:return 5.0
        m=re.search(r"\d+\.?\d*",j["choices"][0]["message"]["content"].strip())
        return min(max(float(m.group()) if m else 5.0,0),10)
    except Exception as e:print(f"Groq error: {e}");return 5.0

RSS_FEEDS=[("wsj_markets","https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),("reuters_biz","https://feeds.reuters.com/reuters/businessNews"),("marketwatch","https://feeds.marketwatch.com/marketwatch/topstories"),("cnbc_top","https://www.cnbc.com/id/100003114/device/rss/rss.html"),("cnbc_earnings","https://www.cnbc.com/id/15839135/device/rss/rss.html")]

def fetch_finnhub(tickers,hours=24):
    if not FINNHUB_API_KEY:return []
    date_from=(datetime.now()-timedelta(hours=hours)).strftime("%Y-%m-%d");date_to=datetime.now().strftime("%Y-%m-%d")
    items=[]
    for ticker in tickers:
        try:
            r=requests.get("https://finnhub.io/api/v1/company-news",params={"symbol":ticker,"from":date_from,"to":date_to,"token":FINNHUB_API_KEY},timeout=8);r.raise_for_status()
            for n in r.json()[:5]:items.append({"source":"finnhub","ticker":ticker,"title":n.get("headline",""),"summary":n.get("summary",""),"url":n.get("url",""),"published":str(n.get("datetime",""))})
            time.sleep(1.5)
        except Exception as e:print(f"Finnhub {ticker} error: {e}")
    print(f"Finnhub: {len(items)} items");return items

def fetch_rss(tickers):
    items=[];ticker_pat={t:re.compile(rf'(?<![A-Z\-]){re.escape(t)}(?![A-Z\-])') for t in tickers if len(t)>=3}
    SKIP_WORDS={'AT','BE','BY','GO','IF','IN','IS','IT','ME','MY','NO','OF','ON','OR','SO','TO','UP','US','WE'}
    ticker_pat={k:v for k,v in ticker_pat.items() if k not in SKIP_WORDS}
    for name,url in RSS_FEEDS:
        try:
            feed=feedparser.parse(url);count=0
            for entry in feed.entries[:20]:
                title=entry.get("title","");summary=entry.get("summary","");text_up=(title+" "+summary).upper()
                matched=next((t for t,pat in ticker_pat.items() if pat.search(text_up)),None)
                if not matched:continue
                items.append({"source":f"rss_{name}","ticker":matched,"title":title,"summary":summary[:200],"url":entry.get("link",""),"published":entry.get("published","")});count+=1
            print(f"RSS {name}: {count} items")
        except Exception as e:print(f"RSS {name} error: {e}")
    return items

TICKER_CIK={"AAPL":"0000320193","MSFT":"0000789019","NVDA":"0001045810","GOOGL":"0001652044","META":"0001326801","AMZN":"0001018724","TSLA":"0001318605","JPM":"0000019617","V":"0001403161","MA":"0001141391","JNJ":"0000200406","UNH":"0000731766","LLY":"0000059478","XOM":"0000034088","BAC":"0000070858","ABBV":"0001551152","MRK":"0000310158","PFE":"0000078003","KO":"0000021344","PG":"0000080424","WMT":"0000104169","HD":"0000354950","COST":"0000909832","NFLX":"0001065280","AMD":"0000002488","INTC":"0000050863","QCOM":"0000804328","CRM":"0001108524","ORCL":"0001341439","ADBE":"0000796343"}

def fetch_edgar(tickers):
    items=[];headers={"User-Agent":"QuantForce research@quantforce.com"};cutoff=datetime.now()-timedelta(hours=48)
    for ticker in tickers:
        cik=TICKER_CIK.get(ticker)
        if not cik:continue
        try:
            r=requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",headers=headers,timeout=10);r.raise_for_status()
            data=r.json();filings=data.get("filings",{}).get("recent",{});forms=filings.get("form",[]);dates=filings.get("filingDate",[]);accnums=filings.get("accessionNumber",[]);descs=filings.get("primaryDocDescription",[])
            for i,form in enumerate(forms[:20]):
                if form not in ("8-K","8-K/A"):continue
                try:filed=datetime.strptime(dates[i],"%Y-%m-%d")
                except:continue
                if filed<cutoff:continue
                acc=accnums[i].replace("-","")
                items.append({"source":"edgar_8k","ticker":ticker,"title":f"{ticker} filed 8-K: {descs[i] if i<len(descs) else ''}","summary":f"SEC 8-K filing on {dates[i]}","url":f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc}/","published":dates[i]})
            time.sleep(0.15)
        except Exception as e:print(f"EDGAR {ticker} error: {e}")
    print(f"EDGAR: {len(items)} 8-K items");return items

def push_to_pg(conn,item,score):
    event_hash=hashlib.md5((item["title"]+item["ticker"]).encode()).hexdigest()
    features={"score":score,"headline":item["title"],"summary":item["summary"][:300],"url":item["url"],"published":item["published"],"source":item["source"],"mode":"secondary"}
    sql="INSERT INTO signals_raw (signal_id,symbol,signal_type,direction,importance,confidence,score,source,pipeline,event_hash,features,expire_at,status) VALUES (%s,%s,'news','buy',%s,0.0,%s,%s,%s,%s,NOW()+INTERVAL %s,'pending') ON CONFLICT (event_hash) DO NOTHING;"
    try:
        with conn.cursor() as cur:cur.execute(sql,(str(uuid.uuid4()),item["ticker"],min(int(score*10),100),score,item["source"],event_hash,json.dumps(features),f"{EXPIRE_HOURS} hours"))
        return True
    except psycopg2.errors.UniqueViolation:conn.rollback();return False
    except Exception as e:print(f"PG写入失败 {item['ticker']}: {e}");conn.rollback();return False

def main():
    print("=== news_scanner_v5 启动（次要条件模式）===")
    tickers=load_whitelist();print(f"白名单: {len(tickers)} 只");seen=set()
    while True:
        print(f"\n--- 新轮次 {datetime.now().strftime('%H:%M:%S')} ---")
        all_items=fetch_finnhub(tickers)+fetch_rss(tickers)+fetch_edgar(tickers)
        print(f"合计 {len(all_items)} 条原始新闻")
        try:
            conn=psycopg2.connect(PG_DSN);queued=0;skipped=0;no_tech=0
            for item in all_items:
                key=hashlib.md5((item["title"]+item["ticker"]).encode()).hexdigest()
                if key in seen:skipped+=1;continue
                seen.add(key)
                if not has_tech_signal(conn,item["ticker"]):no_tech+=1;continue
                score=get_score(item["title"]+" "+item["summary"][:100])
                print(f"[{item['source']}] [{item['ticker']}] score={score:.1f} {item['title'][:55]}")
                if score>=SCORE_THRESH:
                    if push_to_pg(conn,item,score):queued+=1;print(f"  ✅ {item['ticker']} score={score:.1f} (tech+news)")
                if len(seen)>2000:seen=set(list(seen)[-500:])
            conn.commit();conn.close()
            print(f"轮次完成 queued={queued} skipped={skipped} no_tech={no_tech}")
        except Exception as e:print(f"DB error: {e}")
        print(f"等待 {POLL_SEC}s...");time.sleep(POLL_SEC)

if __name__=="__main__":main()
