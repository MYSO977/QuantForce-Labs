#!/bin/bash
set -e
echo "=== 分发股票池 ==="

scp /home/heng/tickers_vision.txt   heng@192.168.0.15:/home/heng/tickers_vision.txt
scp /home/heng/tickers_executor.txt heng@192.168.0.11:/home/heng/tickers_executor.txt
scp /home/heng/tickers_compute.txt  heng@192.168.0.143:/home/heng/tickers_compute.txt

echo "分发完成，重启各节点 scanner..."
ssh heng@192.168.0.15  "sudo systemctl restart tech-scanner"
ssh heng@192.168.0.11  "sudo systemctl restart tech-scanner"
ssh heng@192.168.0.143 "sudo systemctl restart tech-scanner"

echo "=== 全部完成 ==="
