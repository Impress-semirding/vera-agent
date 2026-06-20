#!/usr/bin/env bash
# ============================================================================
# Vera 一键部署脚本
# ============================================================================
# 用法：将本脚本放在仓库根目录，以 root 执行：
#   chmod +x deploy.sh && sudo ./deploy.sh
#
# 做了什么：
#   1. 检查/编译 Python (≥ 3.10)
#   2. 检查/安装 Docker
#   3. 创建 venv + 安装后端依赖
#   4. 安装前端依赖
#   5. 生成 .env + MCP JWT 密钥对
#   6. 构建 Docker 镜像
#
# 不会启动服务 —— 启动命令见脚本末尾提示，或参考 DEPLOY_ALIYUN.md 第六节。
# ============================================================================

set -euo pipefail

# ── 预检 ──────────────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo "请以 root 执行：sudo ./deploy.sh"
    exit 1
fi

for cmd in openssl wget fuser; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "缺少命令: $cmd，请先安装"
        exit 1
    fi
done

# 如果旧服务还在跑，先停掉
echo "检查端口占用 ..."
for port in 3000 18080; do
    if fuser "$port"/tcp &>/dev/null; then
        echo "  端口 $port 被占用，杀掉旧进程 ..."
        fuser -k "$port"/tcp 2>/dev/null || true
    fi
done

# ── 动态路径：自动识别仓库根目录（脚本所在目录）─────────────────────────
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
DATA_DIR="/var/lib/vera"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
LOG_DIR="/var/log"
echo "============================================"
echo " Vera 部署脚本"
echo " 项目目录: $PROJECT_ROOT"
echo "============================================"
echo ""

# ── 1. Python (≥ 3.10) ────────────────────────────────────────────────────
echo "[1/6] 检查 Python ..."

PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
if [ -n "$PYTHON_BIN" ] && "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    echo "  ✓ 找到 $($PYTHON_BIN -V)  ($PYTHON_BIN)"
else
    echo "  未找到 Python ≥ 3.10，开始编译安装 ..."
    yum install -y gcc make openssl-devel bzip2-devel libffi-devel zlib-devel sqlite-devel wget
    cd /tmp
    if [ ! -f Python-3.11.11.tgz ]; then
        wget https://www.python.org/ftp/python/3.11.11/Python-3.11.11.tgz
    fi
    tar xzf Python-3.11.11.tgz
    cd Python-3.11.11
    ./configure --enable-optimizations --prefix=/usr/local/python3.11
    make -j"$(nproc)"
    make altinstall
    PYTHON_BIN="/usr/local/python3.11/bin/python3.11"
    echo "  ✓ Python 安装完成: $($PYTHON_BIN -V)"
fi
echo ""

# ── 2. Docker ─────────────────────────────────────────────────────────────
echo "[2/6] 检查 Docker ..."
if command -v docker &>/dev/null && docker info &>/dev/null; then
    echo "  ✓ Docker 已运行: $(docker --version)"
else
    echo "  未安装，开始安装 ..."
    yum install -y docker
    systemctl start docker && systemctl enable docker
    echo "  ✓ Docker 安装完成"
fi
echo ""

# ── 3. 后端依赖 ──────────────────────────────────────────────────────────
echo "[3/6] 安装后端依赖 ..."
cd "$BACKEND_DIR"

# 创建 venv
if [ ! -d .venv ]; then
    "$PYTHON_BIN" -m venv .venv
    echo "  ✓ venv 已创建"
fi

# 激活 + 配置镜像 + 安装
source .venv/bin/activate
pip config set global.index-url "$MIRROR"
pip install --upgrade pip -i "$MIRROR" --quiet
pip install -e . -i "$MIRROR" --quiet
echo "  ✓ 后端依赖安装完成"
echo ""

# ── 4. 前端依赖 ──────────────────────────────────────────────────────────
echo "[4/6] 安装前端依赖 ..."
if ! command -v node &>/dev/null; then
    echo "  未找到 Node.js，请先安装 Node.js 18+"
    exit 1
fi
cd "$FRONTEND_DIR"
# 确保 pnpm 可用
if ! command -v pnpm &>/dev/null; then
    npm install -g pnpm --silent
fi
pnpm install --silent
echo "  ✓ 前端依赖安装完成"
echo ""

# ── 5. 配置 .env + JWT 密钥对 ────────────────────────────────────────────
echo "[5/6] 配置环境 ..."
cd "$BACKEND_DIR"

# 创建数据目录
mkdir -p "$DATA_DIR"

# .env 由用户手动准备，脚本仅注入 JWT 私钥

# 强制重新生成 JWT 密钥对，并自动写入 .env
echo "  生成 JWT 密钥对 ..."
rm -f mcp_jwt_private.pem mcp_jwt_public.pem
openssl genrsa -out mcp_jwt_private.pem 2048
openssl rsa -in mcp_jwt_private.pem -pubout -out mcp_jwt_public.pem
PRIV_ONELINE="$(awk 'NF{printf "%s\\n",$0}' mcp_jwt_private.pem)"
"$PYTHON_BIN" -c "
import sys
with open('.env','r') as f:
    lines = f.readlines()
with open('.env','w') as f:
    for line in lines:
        if line.startswith('VERA_MCP_JWT_PRIVATE_KEY='):
            f.write('VERA_MCP_JWT_PRIVATE_KEY=' + sys.argv[1] + '\n')
        else:
            f.write(line)
" "$PRIV_ONELINE"
echo "  ✓ 密钥对已生成"
echo "    私钥 → .env (VERA_MCP_JWT_PRIVATE_KEY)"
echo "    公钥 → $BACKEND_DIR/mcp_jwt_public.pem（请拷到 MCP server）"
echo ""

# ── 6. 构建 Docker 镜像 ──────────────────────────────────────────────────
echo "[6/6] 构建 Docker 镜像 ..."
cd "$BACKEND_DIR"
docker build -t vera-agent-runner:latest ./agent_runtime/claude/docker/
echo "  ✓ 镜像构建完成"
echo ""

# ── 完成 ──────────────────────────────────────────────────────────────────
echo "============================================"
echo " 部署完成！"
echo "============================================"
echo ""
echo "启动服务（前台调试）："
echo "  cd $BACKEND_DIR && source .venv/bin/activate"
echo "  AGENT_USE_DOCKER=1 python -m uvicorn api.main:app --host 0.0.0.0 --port 18080"
echo ""
echo "启动服务（后台生产）："
echo "  cd $FRONTEND_DIR"
echo "  nohup npx vite --host 0.0.0.0 --port 3000 > $LOG_DIR/vera-frontend.log 2>&1 & disown"
echo ""
echo "  cd $BACKEND_DIR && source .venv/bin/activate"
echo "  nohup .venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 18080 > $LOG_DIR/vera-backend.log 2>&1 & disown"
echo ""
echo "公钥位置: $BACKEND_DIR/mcp_jwt_public.pem → 请拷到 MCP server"
echo "数据目录: $DATA_DIR"
echo "默认账号: admin / 123456"
