#!/bin/bash
# Vera stop script — kill backend + frontend processes

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/logs"

echo "=== Vera 停止 ==="

# ── Kill by PID file ────────────────────────────────────
for svc in backend frontend; do
    pidfile="$LOG_DIR/${svc}.pid"
    if [ -f "$pidfile" ]; then
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null && echo "  已停止 $svc (pid=$pid)"
        else
            echo "  $svc (pid=$pid) 已不在运行"
        fi
        rm -f "$pidfile"
    fi
done

# ── Fallback: kill by port ──────────────────────────────
function kill_port() {
    local p=$1
    local name=$2
    local pid
    pid=$(ss -tlnp 2>/dev/null | grep ":$p " | sed -n 's/.*pid=\([0-9]*\).*/\1/p')
    if [ -n "$pid" ]; then
        kill -9 "$pid" 2>/dev/null && echo "  已强制停止端口 $p ($name) pid=$pid"
    fi
}

kill_port 18080 "backend"
kill_port 3000  "frontend"

echo "=== 已停止 ==="
