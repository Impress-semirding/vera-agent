#!/bin/bash
# Vera start script — launch backend + frontend with nohup

set -e
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "=== Vera 启动 ==="
echo "项目目录: $PROJECT_DIR"
echo "日志目录: $LOG_DIR"
echo ""

# ── Kill existing processes on target ports ──────────────
function kill_port() {
    local p=$1
    local pid
    pid=$(ss -tlnp 2>/dev/null | grep ":$p " | sed -n 's/.*pid=\([0-9]*\).*/\1/p')
    [ -n "$pid" ] && kill -9 $pid 2>/dev/null && echo "  已清理端口 $p (pid=$pid)"
}

kill_port 18080
kill_port 3000

# ── Backend ──────────────────────────────────────────────
cd "$PROJECT_DIR/backend"

# Create venv + install deps on first run
if [ ! -d ".venv" ]; then
    echo "[0/2] 首次运行：创建虚拟环境 + 安装依赖 ..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e .
    pip install claude-agent-sdk
else
    source .venv/bin/activate
fi

echo "[1/2] 启动后端 (uvicorn :18080) ..."
nohup python -m uvicorn api.main:app --host 0.0.0.0 --port 18080 \
    > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "  backend pid=$BACKEND_PID"
echo $BACKEND_PID > "$LOG_DIR/backend.pid"
sleep 2

# ── Frontend ─────────────────────────────────────────────
cd "$PROJECT_DIR/frontend"
if [ ! -d "node_modules" ]; then
    echo "[0/2] 首次运行：安装前端依赖 ..."
    npm install
fi

echo "[2/2] 启动前端 (vite :3000) ..."
nohup npx vite --host 0.0.0.0 --port 3000 \
    > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "  frontend pid=$FRONTEND_PID"
echo $FRONTEND_PID > "$LOG_DIR/frontend.pid"
sleep 2

echo ""
echo "=== 启动完成 ==="
echo "  前端: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):3000"
echo "  后端: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):18080"
echo "  日志: $LOG_DIR/"
echo ""
echo "查看日志: tail -f $LOG_DIR/backend.log"
echo "停止服务: $PROJECT_DIR/stop.sh"
