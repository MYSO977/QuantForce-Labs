#!/usr/bin/env python3
"""
QuantForce_Labs — phi3_extractor.py
节点: executor (.11)  模型: phi3:mini
职责1: 拉取 event_extract 任务，结构化提取事件
职责2: 拉取 fallback 任务（Groq 失败），本地兜底，score × 0.8
"""
import sqlite3, json, time, hashlib, requests, logging, os, socket

DB_PATH   = os.getenv("LLM_DB", "/home/heng/llm_tasks.db")
OLLAMA    = "http://localhost:11434"
MODEL     = "phi3:mini"
NODE_IP   = socket.gethostbyname(socket.gethostname())
POLL_SEC  = 5
LOCK_TTL  = 120
FALLBACK_SCORE_DISCOUNT = 0.8

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PHI3_EXTRACTOR] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.expanduser("~/logs/phi3_extractor.log"))
    ]
)
log = logging.getLogger(__name__)

EXTRACT_PROMPT = """你是金融事件结构化助手。
从输入文本提取关键事件信息。
严格只输出 JSON，不要任何解释：
{
  "ticker": "股票代码或null",
  "event_type": "earnings|merger|guidance|macro|other",
  "direction": "positive|negative|neutral",
  "magnitude": "high|medium|low",
  "date_mentioned": "提到的日期或null",
  "key_numbers": ["提到的关键数字"],
  "summary": "一句话摘要（英文）",
  "l1_score_estimate": 0.0
}
l1_score_estimate 范围 0-10，10 分代表极高市场影响力。"""

FALLBACK_PROMPT = """你是量化交易信号分析助手。
基于以下新闻事件，给出交易信号决策。
严格只输出 JSON，不要任何解释：
{
  "action": "BUY|SELL|HOLD",
  "size": 0.05,
  "confidence": 0.0,
  "reasoning": "简短理由",
  "source": "fallback_phi3",
  "low_confidence": true
}
size 范围 0.01-0.10，confidence 范围 0.0-1.0。"""

def get_conn():
    return sqlite3.connect(DB_PATH, timeout=20)

def claim_task(conn, task_type, status="pending"):
    cur = conn.cursor()
    # 回收超时锁
    cur.execute("""
        UPDATE llm_tasks SET status=?, locked_by=NULL, locked_at=NULL
        WHERE task_type=? AND status=?
          AND locked_by IS NOT NULL
          AND (julianday('now') - julianday(locked_at)) * 86400 > ?
    """, (status, task_type, status, LOCK_TTL))
    # 认领
    cur.execute("""
        SELECT id, input_text, score FROM llm_tasks
        WHERE task_type=? AND status=? AND locked_by IS NULL
        ORDER BY created_at ASC LIMIT 1
    """, (task_type, status))
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

def call_phi3(text, prompt):
    t0 = time.time()
    resp = requests.post(f"{OLLAMA}/api/chat", json={
        "model": MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user",   "content": text[:2000]}
        ],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 512}
    }, timeout=60)
    resp.raise_for_status()
    content = resp.json()["message"]["content"].strip()
    latency = int((time.time() - t0) * 1000)
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content), latency

def process_extract(conn, task_id, input_text):
    """处理 event_extract 任务"""
    try:
        result, latency = call_phi3(input_text, EXTRACT_PROMPT)
        score = float(result.get("l1_score_estimate", 0))
        cur = conn.cursor()
        cur.execute("""
            UPDATE llm_tasks
            SET status='done', node=?, model=?, output_json=?,
                score=?, latency_ms=?, locked_by=NULL, locked_at=NULL
            WHERE id=?
        """, (NODE_IP, MODEL, json.dumps(result, ensure_ascii=False),
              score, latency, task_id))
        conn.commit()
        log.info(f"[{task_id}] extract done  latency={latency}ms  score={score:.1f}  ticker={result.get('ticker')}")
    except Exception as e:
        log.error(f"[{task_id}] extract failed: {e}")
        cur = conn.cursor()
        cur.execute("""
            UPDATE llm_tasks
            SET status='failed', output_json=?, locked_by=NULL, locked_at=NULL
            WHERE id=?
        """, (json.dumps({"error": str(e)}), task_id))
        conn.commit()

def process_fallback(conn, task_id, input_text, original_score):
    """处理 Groq fallback 任务，score × 0.8"""
    try:
        result, latency = call_phi3(input_text, FALLBACK_PROMPT)
        result["source"] = "fallback_phi3"
        result["low_confidence"] = True
        # score 折扣
        base_score = original_score or float(result.get("confidence", 0.5)) * 10
        discounted_score = round(base_score * FALLBACK_SCORE_DISCOUNT, 2)
        result["discounted_score"] = discounted_score
        cur = conn.cursor()
        cur.execute("""
            UPDATE llm_tasks
            SET status='done', node=?, model=?, output_json=?,
                score=?, latency_ms=?, locked_by=NULL, locked_at=NULL
            WHERE id=?
        """, (NODE_IP, MODEL, json.dumps(result, ensure_ascii=False),
              discounted_score, latency, task_id))
        conn.commit()
        log.info(f"[{task_id}] fallback done  latency={latency}ms  score={discounted_score}  action={result.get('action')}")
    except Exception as e:
        log.error(f"[{task_id}] fallback failed: {e}")
        cur = conn.cursor()
        cur.execute("""
            UPDATE llm_tasks
            SET status='failed', output_json=?, locked_by=NULL, locked_at=NULL
            WHERE id=?
        """, (json.dumps({"error": str(e)}), task_id))
        conn.commit()

def main():
    log.info(f"Phi3 Extractor 启动  node={NODE_IP}  model={MODEL}  db={DB_PATH}")
    try:
        r = requests.get(f"{OLLAMA}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        if not any(MODEL in m for m in models):
            log.warning(f"模型 {MODEL} 未找到，请先 ollama pull {MODEL}")
    except Exception as e:
        log.error(f"Ollama 连接失败: {e}")

    while True:
        try:
            conn = get_conn()
            # 优先处理 fallback（紧急兜底）
            task_id, input_text, score = claim_task(conn, "signal_decision", "fallback")
            if task_id:
                log.info(f"[{task_id}] 认领 fallback 任务")
                process_fallback(conn, task_id, input_text or "", score)
            else:
                # 处理常规 event_extract
                task_id, input_text, _ = claim_task(conn, "event_extract")
                if task_id:
                    log.info(f"[{task_id}] 认领 event_extract 任务")
                    process_extract(conn, task_id, input_text or "")
            conn.close()
        except Exception as e:
            log.error(f"主循环异常: {e}")
        time.sleep(POLL_SEC)

if __name__ == "__main__":
    os.makedirs(os.path.expanduser("~/logs"), exist_ok=True)
    main()
