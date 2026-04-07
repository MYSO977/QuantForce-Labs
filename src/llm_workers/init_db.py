#!/usr/bin/env python3
"""
QuantForce_Labs — init_db.py
在 center (.18) 上运行一次，初始化 llm_tasks.db
用法: python3 init_db.py
"""
import sqlite3
import os

DB_PATH = os.path.expanduser("~/llm_tasks.db")

DDL = """
CREATE TABLE IF NOT EXISTS llm_tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type    TEXT NOT NULL,
    node         TEXT,
    model        TEXT,
    input_hash   TEXT,
    input_text   TEXT,
    output_json  TEXT,
    score        REAL,
    latency_ms   INTEGER,
    status       TEXT DEFAULT 'pending',
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    locked_by    TEXT,
    locked_at    DATETIME
);

CREATE INDEX IF NOT EXISTS idx_status_type ON llm_tasks(status, task_type);
CREATE INDEX IF NOT EXISTS idx_input_hash  ON llm_tasks(input_hash);
CREATE INDEX IF NOT EXISTS idx_created_at  ON llm_tasks(created_at);

CREATE TRIGGER IF NOT EXISTS trg_updated_at
AFTER UPDATE ON llm_tasks
BEGIN
    UPDATE llm_tasks SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""

def init():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.executescript(DDL)
    conn.commit()
    conn.close()
    print(f"[init_db] DB 初始化完成: {DB_PATH}")

if __name__ == "__main__":
    init()
