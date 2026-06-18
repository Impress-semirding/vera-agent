# Vera 阿里云 Linux 部署指南

## 一、升级 Python 3.11

```bash
# 编译依赖（sqlite-devel 必须有，否则缺 _sqlite3 模块）
yum install -y gcc make openssl-devel bzip2-devel libffi-devel zlib-devel sqlite-devel wget

# 下载 + 编译
cd /tmp
wget https://www.python.org/ftp/python/3.11.11/Python-3.11.11.tgz
tar xzf Python-3.11.11.tgz
cd Python-3.11.11
./configure --enable-optimizations --prefix=/usr/local/python3.11
make -j$(nproc)
make altinstall
/usr/local/python3.11/bin/python3.11 -V
```

---

## 二、安装 Docker

```bash
yum install -y docker
systemctl start docker && systemctl enable docker
```

---

## 三、部署项目

```bash
cd /home/vera-agent-main/backend

# venv + 依赖
/usr/local/python3.11/bin/python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple/
pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple/
pip install claude-agent-sdk qrcode Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple/

# 前端
cd ../frontend && npm install
```

---

## 四、配置 .env

```bash
cat > /home/vera-agent-main/backend/.env << 'EOF'
VERA_DATA_DIR=/var/lib/vera
VERA_SESSION_SECRET=<改成随机64位字符串>
VERA_SEED_USERS=admin:admin@example.com:123456
AGENT_USE_DOCKER=1
AGENT_DOCKER_IMAGE=vera-agent-runner:latest
AGENT_MAX_CONCURRENT_TURNS=2

# DingTalk OAuth（可选）
DINGTALK_APP_KEY=
DINGTALK_APP_SECRET=
DINGTALK_REDIRECT_URI=http://你的IP:3000/login/dingtalk/callback

# OSS 文件上传（可选）
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
OSS_BUCKET_NAME=
OSS_ENDPOINT=
OSS_BASE_URL=
EOF

mkdir -p /var/lib/vera
```

---

## 五、构建 Docker 镜像

```bash
cat > /home/vera-agent-main/backend/agent_runtime/claude/docker/Dockerfile << 'EOF'
FROM alibaba-cloud-linux-3-registry.cn-hangzhou.cr.aliyuncs.com/alinux3/python:3.11.1

RUN yum install -y git curl ca-certificates && yum clean all

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir claude-agent-sdk

RUN useradd -m -s /bin/bash agent && \
    mkdir -p /workspace /home/agent/.claude && \
    chown -R agent:agent /workspace /home/agent

COPY runner.py stream_emitter.py /app/

ENV PYTHONPATH=/app
WORKDIR /workspace
USER agent

ENTRYPOINT ["python3", "/app/runner.py"]
EOF

docker build -t vera-agent-runner:latest /home/vera-agent-main/backend/agent_runtime/claude/docker/
```

---

## 六、启动（nohup + disown，关终端不挂）

> **关键**：`nohup` + `disown` + 输出重定向到文件，三者缺一不可。

```bash
# ── 前端 ──────────────────────────────────────
cd /home/vera-agent-main/frontend
nohup npx vite --host 0.0.0.0 --port 3000 > /var/log/vera-frontend.log 2>&1 &
disown

# ── 后端 ──────────────────────────────────────
cd /home/vera-agent-main/backend
source .venv/bin/activate
nohup .venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 18080 > /var/log/vera-backend.log 2>&1 &
disown

# ── 验证 ──────────────────────────────────────
sleep 3
curl -s http://127.0.0.1:3000/ | head -3
curl -s http://127.0.0.1:18080/health
```

### 停止
```bash
fuser -k 3000/tcp
pkill -f "uvicorn api.main"
```

### 重启
```bash
fuser -k 3000/tcp; pkill -f "uvicorn api.main"
# 再跑上面的启动命令
```

### 日志
```bash
tail -f /var/log/vera-backend.log
tail -f /var/log/vera-frontend.log
```

---

## 七、阿里云安全组

控制台 → ECS → 安全组 → 入方向：

| 端口 | 用途 |
|------|------|
| 3000 | 前端 |
| 18080 | 后端 API |

---

## 八、MCP Server 部署（HTTP 模式）

以 FRED MCP Server 为例，独立 HTTP 服务跑在宿主机，Docker 容器通过 `127.0.0.1` 访问（Linux Docker 用 `--network host`，容器内 localhost = 宿主机）。

```bash
# 启动 MCP server（nohup 后台）
cd /home/fred-mcp-server-main
nohup env PORT=3003 FRED_API_KEY=你的key node build/index.js --http > /var/log/fred-mcp.log 2>&1 &
disown

# 验证
sleep 1
curl -s http://127.0.0.1:3003/ | head -3
```

在 Vera 前端 → Agent → 工具配置 → 添加 MCP Server：

| 字段 | 值 |
|------|-----|
| 名称 | FRED MCP Server |
| Transport | http |
| URL | http://127.0.0.1:3003 |

> MCP server 的 FRED_API_KEY 在启动时通过 env 传入，不需要在 Vera 里配。
> 多个 agent 可共用同一个 MCP server 实例。

---

## 九、常见问题

### `_sqlite3` 模块缺失
编译 Python 前没装 `sqlite-devel`：
```bash
yum install -y sqlite-devel
cd /tmp/Python-3.11.11 && make clean
./configure --enable-optimizations --prefix=/usr/local/python3.11
make -j$(nproc) && make altinstall
# 然后重建 .venv
```

### pip 装包超时 / 找不到版本
```bash
pip install xxx -i https://pypi.tuna.tsinghua.edu.cn/simple/
```

### Docker 拉镜像失败（Docker Hub 被墙）
```bash
# 阿里云官方镜像（直接拉，不需要 Docker Hub）
docker pull alibaba-cloud-linux-3-registry.cn-hangzhou.cr.aliyuncs.com/alinux3/python:3.11.1
```

### 关终端后服务挂了
确保用了 `disown`（不只是 `nohup`），输出重定向到文件而非 tty。

### 容器内权限拒绝 `EACCES`
宿主机以 root 创建的目录，容器内 `agent` 用户没写权限。代码已自动 `chmod 777`，如果仍报错：
```bash
chmod -R 777 /var/lib/vera/workspaces/
```

### 第二条消息报错（SDK session resume 冲突）
```bash
# 关闭 session resume（服务器上）
sed -i 's/if _session_id:/if False:/' /home/vera-agent-main/backend/agent_runtime/claude/docker/runner.py
docker build -t vera-agent-runner:latest /home/vera-agent-main/backend/agent_runtime/claude/docker/
# 重启后端
```
