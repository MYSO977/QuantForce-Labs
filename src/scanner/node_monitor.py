#!/usr/bin/env python3
import json, time
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess

def get_stats():
    # CPU 1秒采样
    cpu = float(subprocess.run(
        ['python3','-c','import psutil,time; t1=psutil.cpu_times(); time.sleep(1); t2=psutil.cpu_times(); idle=t2.idle-t1.idle; total=sum(t2)-sum(t1); print(round((1-idle/total)*100,1))'],
        capture_output=True, text=True).stdout.strip() or 0)
    # 内存
    mem = subprocess.run(
        ['python3','-c','import psutil; m=psutil.virtual_memory(); print(round(m.percent,1))'],
        capture_output=True, text=True).stdout.strip()
    return {'cpu': cpu, 'mem': float(mem or 0)}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/stats':
            data = get_stats()
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, *args): pass

HTTPServer(('0.0.0.0', 9100), Handler).serve_forever()
