#!/bin/bash
# deploy.sh — QuantForce Labs 一键部署
# 用法: ./deploy.sh [all|.11|.15|.143]
# 从 .18 推送代码到各节点并重启服务

set -e
REPO="$HOME/QuantForce_Labs"
NODES=("192.168.0.11" "192.168.0.15" "192.168.0.143")
TARGET=${1:-all}

log() { echo "[DEPLOY] $(date '+%H:%M:%S') $*"; }

deploy_11() {
    log ">>> .11 Dell/executor"
    scp $REPO/ib_executor_v2.py heng@192.168.0.11:~/QuantForce_Labs/
    scp $REPO/src/core/interfaces.py heng@192.168.0.11:~/QuantForce_Labs/src/core/
    ssh heng@192.168.0.11 "sudo systemctl restart ib_executor_v2 account_state_pusher"
    log ".11 完成"
}

deploy_15() {
    log ">>> .15 Vision/scanner"
    ssh heng@192.168.0.15 "cd ~/QuantForce_Labs 2>/dev/null || cd /home/heng/quant/vision"
    scp /home/heng/quant/vision/news_scanner.py heng@192.168.0.15:~/quant/vision/ 2>/dev/null || true
    scp $REPO/src/core/interfaces.py heng@192.168.0.15:~/QuantForce_Labs/src/core/ 2>/dev/null || true
    ssh heng@192.168.0.15 "sudo systemctl restart tech_scanner news_scanner 2>/dev/null || true"
    log ".15 完成"
}

deploy_143() {
    log ">>> .143 Compute"
    ssh heng@192.168.0.143 "echo ok" 2>/dev/null || { log ".143 不可达，跳过"; return; }
    log ".143 完成（无需部署）"
}

deploy_18() {
    log ">>> .18 Acer/center（本机）"
    sudo systemctl restart signal_fusion
    log ".18 signal_fusion 重启完成"
}

case $TARGET in
    all)
        deploy_18
        deploy_11
        deploy_15
        deploy_143
        ;;
    .11) deploy_11 ;;
    .15) deploy_15 ;;
    .143) deploy_143 ;;
    .18) deploy_18 ;;
    *)
        echo "用法: ./deploy.sh [all|.11|.15|.143|.18]"
        exit 1
        ;;
esac

log "=== 部署完成 ==="