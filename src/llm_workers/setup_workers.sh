#!/bin/bash
# ============================================
# QuantForce_Labs — setup_workers.sh
# 在各节点上运行，自动识别节点 IP 并部署对应 worker
# 用法: bash setup_workers.sh
# ============================================

GREEN='\033[0;32m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()  { echo -e "  ${GREEN}✓${NC} $1"; }
err() { echo -e "  ${RED}✗${NC} $1"; }
sec() { echo -e "\n${CYAN}▶ $1${NC}"; }

MY_IP=$(hostname -I | awk '{print $1}')
WORKERS_DIR="/home/heng/llm_workers"
DB_PATH="/home/heng/llm_tasks.db"

echo "============================================"
echo "  QuantForce_Labs Worker 部署"
echo "  节点 IP: $MY_IP"
echo "============================================"

# ── 公共：建目录 ──────────────────────────────
sec "准备目录"
mkdir -p "$WORKERS_DIR" ~/logs
ok "目录就绪: $WORKERS_DIR"

# ── 公共：安装 Python 依赖 ────────────────────
sec "Python 依赖"
pip3 install pyzmq requests groq --quiet 2>/dev/null || \
pip3 install pyzmq requests groq --quiet --break-system-packages 2>/dev/null
ok "依赖安装完成"

# ── 节点分支部署 ──────────────────────────────
case "$MY_IP" in

  # ── center .18 ────────────────────────────
  "192.168.0.18")
    sec "Center (.18) — 初始化 DB + Groq Decision"

    # 初始化数据库
    if [ ! -f "$DB_PATH" ]; then
      python3 "$WORKERS_DIR/init_db.py"
      ok "DB 初始化完成: $DB_PATH"
    else
      ok "DB 已存在: $DB_PATH"
    fi

    # systemd: groq_decision
    sudo bash -c "cat > /etc/systemd/system/quant-groq.service << 'EOF'
[Unit]
Description=QuantForce Groq Decision Worker
After=network.target quant-dispatcher.service

[Service]
Type=simple
User=heng
WorkingDirectory=$WORKERS_DIR
EnvironmentFile=/home/heng/.quant_env
Environment=LLM_DB=$DB_PATH
ExecStart=/usr/bin/python3 $WORKERS_DIR/groq_decision.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF"
    sudo systemctl daemon-reload
    sudo systemctl enable quant-groq
    sudo systemctl restart quant-groq
    sleep 2
    systemctl is-active --quiet quant-groq && ok "quant-groq running" || err "quant-groq 启动失败"
    ;;

  # ── executor .11 ──────────────────────────
  "192.168.0.11")
    sec "Executor (.11) — Phi3 Extractor"

    # 确认 phi3:mini
    ollama list 2>/dev/null | grep -q "phi3:mini" && ok "phi3:mini 已安装" || {
      err "phi3:mini 未安装，正在拉取..."
      ollama pull phi3:mini
    }

    sudo bash -c "cat > /etc/systemd/system/quant-phi3.service << 'EOF'
[Unit]
Description=QuantForce Phi3 Extractor Worker
After=network.target ollama.service

[Service]
Type=simple
User=heng
WorkingDirectory=$WORKERS_DIR
Environment=LLM_DB=$DB_PATH
ExecStart=/usr/bin/python3 $WORKERS_DIR/phi3_extractor.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF"
    sudo systemctl daemon-reload
    sudo systemctl enable quant-phi3
    sudo systemctl restart quant-phi3
    sleep 2
    systemctl is-active --quiet quant-phi3 && ok "quant-phi3 running" || err "quant-phi3 启动失败"
    ;;

  # ── compute .143 ──────────────────────────
  "192.168.0.143")
    sec "Compute (.143) — Qwen Cleaner"

    ollama list 2>/dev/null | grep -q "qwen2.5:0.5b" && ok "qwen2.5:0.5b 已安装" || {
      err "qwen2.5:0.5b 未安装，正在拉取..."
      ollama pull qwen2.5:0.5b
    }

    sudo bash -c "cat > /etc/systemd/system/quant-qwen.service << 'EOF'
[Unit]
Description=QuantForce Qwen Cleaner Worker
After=network.target ollama.service

[Service]
Type=simple
User=heng
WorkingDirectory=$WORKERS_DIR
Environment=LLM_DB=$DB_PATH
ExecStart=/usr/bin/python3 $WORKERS_DIR/qwen_cleaner.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF"
    sudo systemctl daemon-reload
    sudo systemctl enable quant-qwen
    sudo systemctl restart quant-qwen
    sleep 2
    systemctl is-active --quiet quant-qwen && ok "quant-qwen running" || err "quant-qwen 启动失败"
    ;;

  *)
    err "未识别的节点 IP: $MY_IP"
    echo "  支持的节点: 192.168.0.18 / .11 / .143"
    exit 1
    ;;
esac

echo ""
echo "============================================"
echo -e "  ${GREEN}部署完成${NC}  节点: $MY_IP"
echo "============================================"
echo ""
echo "查看日志:"
echo "  journalctl -u quant-groq -f     # .18"
echo "  journalctl -u quant-phi3 -f     # .11"
echo "  journalctl -u quant-qwen  -f    # .143"
