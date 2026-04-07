#!/usr/bin/env python3
"""
QuantForce_Labs — groq_decision.py
节点: center (.18)  模型: llama-3.1-8b-instant (Groq)
职责: 拉取 signal_decision 任务，L1 评分 ≥7.5 才触发
      超时/失败自动降级为 fallback，由 .11 兜底
"""
import sqlite3, json, time, logging, os, socket
from groq import Groq

DB_PATH       = os.getenv("LLM_DB", "/home/heng/llm_tasks.db")
GROQ_API_KEY  = os.getenv("GROQ_API_KEY")
GROQ_MODEL    = "llama-3.1-8b-instant"
NODE_IP       = socket.gethostbyname(socket.gethostname())
POLL_SEC      = 5
LOCK_TTL      = 60    # Groq 任务锁较短
GROQ_TIMEOUT  = 10    # 秒，超时降级
L1_MIN_SCORE  = 7.5   # 低于此分不触发 Groq

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GROQ_DECISION] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.expanduser("~/logs/groq_decision.log"))
    ]
)
log = logging.getLogger(__name__)

DECISION_PROMPT = """你是量化交易信号决策助手。
基于提供的金融事件 JSON，给出交易信号。

严格只输出 JSON，不要任何解释：
{
  "action": "BUY|SELL|HOLD",
  "ticker": "股票代码",
  "size": 0.05,
  "confidence": 0.0,
  "l1_score": 0.0,
  "reasoning": "简短理由（英文）",
  "risk_level": "high|medium|low",
  "source": "groq",
  "low_confidence": false
}
size 范围 0.01-0.10，confidence 范围 0.0-1.0，l1_score 范围 0-10。"""

def get_conn():
    return sqlite3.connect(DB_PATH, timeout=20)

def claim_task(conn):
    cur = conn.cursor()
    # 回收超时锁
    cur.execute("""
        UPDATE llm_tasks SET status='pending', locked_by=NULL, locked_at=NULL
        WHERE task_type='signal_decision' AND status='pending'
          AND locked_by IS NOT NULL
          AND (julianday('now') - julianday(locked_at)) * 86400 > ?
    """, (LOCK_TTL,))
    # 只认领 score >= L1_MIN_SCORE 的任务
    cur.execute("""
        SELECT id, input_text, score FROM llm_tasks
        WHERE task_type='signal_decision'
          AND status='pending'
          AND locked_by IS NULL
          AND (score IS NULL OR score >= ?)
        ORDER BY score DESC, created_at ASC LIMIT 1
    """, (L1_MIN_SCORE,))
    row = cur.fetchone()
    if not row:
        conn.commit()
        return None, None, None
    task_id, input_text, score = row
    cur.execute("""
        UPDATE llm_tasks SET locked_by=?, locked_at=CURRENT_TIMESTAMP
        WHERE id=? AND locked_by IS NULL
    """, (NODE_IP, task_id))
    conn.commit()
    return task_id, input_text, score

def call_groq(client, text):
    t0 = time.time()
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": DECISION_PROMPT},
            {"role": "user",   "content": text[:3000]}
        ],
        max_tokens=512,
        temperature=0.1,
        timeout=GROQ_TIMEOUT
    )
    content = resp.choices[0].message.content.strip()
    latency = int((time.time() - t0) * 1000)
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content), latency

def mark_fallback(conn, task_id, reason):
    """降级：交给 .11 的 phi3 兜底"""
    cur = conn.cursor()
    cur.execute("""
        UPDATE llm_tasks
        SET status='fallback', node='groq',
            output_json=?, locked_by=NULL, locked_at=NULL
        WHERE id=?
    """, (json.dumps({"fallback_reason": reason}), task_id))
    conn.commit()
    log.warning(f"[{task_id}] → fallback  reason={reason}")

def process(conn, client, task_id, input_text, score):
    try:
        result, latency = call_groq(client, input_text)
        result["source"] = "groq"
        result["low_confidence"] = result.get("confidence", 1.0) < 0.6
        cur = conn.cursor()
        cur.execute("""
            UPDATE llm_tasks
            SET status='done', node=?, model=?, output_json=?,
                score=?, latency_ms=?, locked_by=NULL, locked_at=NULL
            WHERE id=?
        """, ("groq", GROQ_MODEL,
              json.dumps(result, ensure_ascii=False),
              result.get("l1_score", score), latency, task_id))
        conn.commit()
        log.info(f"[{task_id}] done  latency={latency}ms  action={result.get('action')}  "
                 f"confidence={result.get('confidence')}  low_confidence={result.get('low_confidence')}")

        # 推送到 dispatcher（ZMQ）如果是 BUY/SELL
        if result.get("action") in ("BUY", "SELL") and not result.get("low_confidence"):
            push_to_dispatcher(result)

    except Exception as e:
        err = str(e)
        log.error(f"[{task_id}] Groq 调用失败: {err}")
        mark_fallback(conn, task_id, err)

def push_to_dispatcher(result):
    """把通过决策的信号推送到 dispatcher:5556"""
    try:
        import zmq
        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.PUSH)
        sock.connect("tcp://127.0.0.1:5556")
        sock.send_json({
            "ticker": result.get("ticker", ""),
            "score":  result.get("l1_score", 0),
            "rvol":   result.get("rvol", 2.0),   # 默认值，上游应填充
            "price":  result.get("price", 0),
            "vwap":   result.get("vwap", 0),
            "macd":   result.get("macd", 0),
            "action": result.get("action"),
            "source": "groq_decision",
        })
        sock.close()
        log.info(f"  → 信号已推送到 dispatcher: {result.get('ticker')} {result.get('action')}")
    except Exception as e:
        log.error(f"  → dispatcher 推送失败: {e}")

def main():
    if not GROQ_API_KEY:
        log.error("GROQ_API_KEY 未设置，请检查 ~/.quant_env")
        return

    client = Groq(api_key=GROQ_API_KEY)
    log.info(f"Groq Decision 启动  node={NODE_IP}  model={GROQ_MODEL}  "
             f"L1_min={L1_MIN_SCORE}  db={DB_PATH}")

    while True:
        try:
            conn = get_conn()
            task_id, input_text, score = claim_task(conn)
            if task_id:
                log.info(f"[{task_id}] 认领任务  score={score}")
                process(conn, client, task_id, input_text or "", score or 0)
            conn.close()
        except Exception as e:
            log.error(f"主循环异常: {e}")
        time.sleep(POLL_SEC)

if __name__ == "__main__":
    os.makedirs(os.path.expanduser("~/logs"), exist_ok=True)
    main()
