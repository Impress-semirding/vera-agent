# Vera 阿里云 Linux 部署指南

> 🚀 **一键部署**：`chmod +x deploy.sh && sudo ./deploy.sh`
> 脚本自动完成下面一到五节全部操作。完成后按第六节手动启动服务。

> 整体拓扑：**前端(vite:3000)** + **后端(uvicorn:18080)** 跑在宿主机；后端按需拉起 **Docker 容器**执行 agent。
> agent 与 MCP server 之间是**双向调用**：
> - **出站**：agent 调用 MCP server。`http/sse` 走 **JWT 签名鉴权**（本指南重点），`stdio` 走 env 注入。
> - **入站**：stdio MCP server（如内置 `vera-scheduler`）回调后端 REST API，用注入的 `VERA_TOKEN`。
>
> 鉴权模型详见 [八、MCP Server 部署与鉴权](#八mcp-server-部署与鉴权)。

---

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

# 前端
cd ../frontend && pnpm install && pnpm run build
```

---

## 四、配置 .env

```bash
cat > /home/vera-agent-main/backend/.env << 'EOF'
VERA_DATA_DIR=/var/lib/vera
# Session token 签名密钥：生产必须改成随机 64 位字符串（用于 stdio MCP 回调鉴权）
VERA_SESSION_SECRET=<改成随机64位字符串>
VERA_SEED_USERS=admin:admin@example.com:123456
AGENT_USE_DOCKER=1
AGENT_DOCKER_IMAGE=vera-agent-runner:latest
AGENT_MAX_CONCURRENT_TURNS=2

# ── 出站 http/sse MCP 的 JWT 签名鉴权（RS256）──────────────────────────────
# 私钥用于给 agent 调 http/sse MCP 的请求签 JWT（Authorization: Bearer <jwt>）；
# 配对的【公钥】部署到 MCP server 侧做验签。未填私钥 → JWT 注入被静默关闭。
# 私钥填法见下方「生成 MCP JWT 密钥对」，强烈建议先生成密钥再回来填。
VERA_MCP_JWT_PRIVATE_KEY=
# 签发方标识：必须与 MCP server 侧验签时声明的 issuer 一致
VERA_MCP_JWT_ISSUER=vera-agent
# JWT 有效期（秒）：需 ≥ 单次会话最长时长，否则会话中途 token 失效
VERA_MCP_JWT_TTL=3600

# LLM Provider（可选，normal 引擎用）
# DEEPSEEK_API_KEY=sk-your-key
# DEEPSEEK_BASE_URL=https://api.deepseek.com

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

### 生成 MCP JWT 密钥对（http/sse MCP 需要签名鉴权时必做）

Vera 侧只持**私钥**（签 JWT），MCP server 侧持**公钥**（验签）。两边是同一对 RSA 密钥。

```bash
cd /home/vera-agent-main/backend

# 1) 生成 RSA 2048 私钥
openssl genrsa -out mcp_jwt_private.pem 2048

# 2) 从私钥导出配对公钥（拷给 MCP server / 资源服务器验签用）
openssl rsa -in mcp_jwt_private.pem -pubout -out mcp_jwt_public.pem
```

> 📌 **关于私钥格式**：现代 `openssl`（macOS libressl、服务器 OpenSSL 3.x）
> `genrsa` 默认输出 **PKCS#8** 的 `-----BEGIN PRIVATE KEY-----`；老版本才是
> `-----BEGIN RSA PRIVATE KEY-----`（PKCS#1）。**两种 PyJWT/cryptography 都能签 RS256**，
> 不用纠结。想要老格式可加 `-traditional`：`openssl genrsa -traditional -out ... 2048`。

**把私钥写进 `.env`**：代码读取时会把字面 `\n` 还原为真实换行
（见 `backend/api/mcp_jwt.py`），所以 `.env` 里必须是**单行、换行写作字面 `\n`** 的形式
（这也是 systemd `EnvironmentFile=` 唯一支持的写法）。用下面命令产出单行串：

```bash
awk 'NF{printf "%s\\n",$0}' mcp_jwt_private.pem; echo
```

复制整行输出，编辑 `.env`，粘到 `VERA_MCP_JWT_PRIVATE_KEY=` 后面，例如：

```
VERA_MCP_JWT_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----
```

> ⚠️ 私钥**绝不入库 / 不进 git**（`.gitignore` 已忽略 `.env` 与 `*.pem`）。
> `mcp_jwt_public.pem` 拷到 MCP server 那台机器（可走 scp / OSS / 密钥管理服务）。

---

## 五、构建 Docker 镜像

> Dockerfile 已随仓库自带（路径：
> `backend/agent_runtime/claude/docker/Dockerfile`），
> 内含 `pip install claude-agent-sdk mcp`、拷贝
> `runner.py stream_emitter.py vera_scheduler_mcp.py` 等全部 3 个文件。
> **不需要**手工创建 Dockerfile，直接构建即可。

```bash
cd /home/vera-agent-main/backend
docker build -t vera-agent-runner:latest ./agent_runtime/claude/docker/
```

> 容器**不需要**私钥：JWT 由宿主机后端签好，随 SDK 的 HTTP 请求头发出，私钥从不进容器。

---

## 六、启动（nohup + disown，关终端不挂）

> **关键**：`nohup` + `disown` + 输出重定向到文件，三者缺一不可。

```bash
# ── 前端 ──────────────────────────────────────
cd /home/vera-agent-main/frontend
nohup npx vite preview --host 0.0.0.0 --port 3000 > /var/log/vera-frontend.log 2>&1 &
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

> http/sse MCP server 若跑在独立端口（见第八节），其端口**只在宿主机内部用**，**不要**开到安全组——agent 容器走 `127.0.0.1` 访问即可。

---

## 八、MCP Server 部署与鉴权

agent 与 MCP 之间有**两条互不相关**的鉴权路径，先看清楚用哪条：

| 模型 | transport | 谁来验证 | 凭证形态 | 需要配置吗 |
|------|-----------|----------|----------|-----------|
| **A. JWT 签名** | `http` / `sse` / `streamable-http` | **MCP server**（持 RSA **公钥**验签） | 请求头 `Authorization: Bearer <jwt>`，Vera 用**私钥**签发 | ✅ 需生成密钥对（第四节） |
| **B. VERA_TOKEN 回调** | `stdio` | **Vera 后端**（持 `VERA_SESSION_SECRET`） | env `VERA_TOKEN`，MCP 回调后端 REST 时带上 | ❌ 始终自动开启 |

> 判断依据：MCP server 是不是 HTTP 服务？
> - **是**（独立进程监听端口）→ 走**模型 A**，Vera 用私钥签 JWT，MCP 用公钥验签。
> - **否**（被 agent 当子进程拉起的 stdio server，如内置 `vera-scheduler`）→ 走**模型 B**，无需 JWT。

### 8.1 模型 A：http/sse MCP + JWT 签名鉴权

**前提**：第四节已生成密钥对，私钥已填进 `.env` 的 `VERA_MCP_JWT_PRIVATE_KEY`，
公钥 `mcp_jwt_public.pem` 已拷到 MCP server。

#### (1) Vera 侧（签 JWT，自动）

无需手动配置每个 server。后端 `agent_runtime/claude/config.py` 会在每次出站 http/sse 调用时：

1. 检查 `is_mcp_jwt_enabled()`（私钥非空才为真）；
2. 用私钥按 **RS256** 签一个 JWT，claims 为：
   - `iss` = `VERA_MCP_JWT_ISSUER`（默认 `vera-agent`）
   - `sub` = 当前 `user_id`
   - **`aud` = 该 MCP server 在 Vera DB 里的 `name`**（关键耦合点，见下）
   - `exp` = `iat + VERA_MCP_JWT_TTL`
3. 注入到请求头 `Authorization: Bearer <jwt>`。

> ⚠️ **JWT 注入是全局开关**：私钥一旦配置，**所有** http/sse MCP server 都会被注入该头，
> 且会**覆盖**该 server 在数据库里预置的 `Authorization` 头（代码无条件赋值）。
> 若某个 http server 不需要签名鉴权（用自身 API key），把它改成 `stdio` 或单独部署、关闭全局 JWT。

#### (2) MCP server 侧（用公钥验签）

MCP server 收到请求后，**判断 `Authorization` 头里的 JWT 是否能用自己持有的公钥验签通过**——
通过即说明它是由配对私钥（即 Vera）签发的，放行；否则 401。

最小验签示例（Python / PyJWT，与 Vera 签发端对称）：

```python
# 在 MCP server 启动时加载公钥
import os, jwt
from jwt import PyJWTError

PUB = open(os.environ["JWT_PUBLIC_KEY_PATH"]).read()   # mcp_jwt_public.pem 内容
EXPECT_ISS = os.environ.get("JWT_ISSUER", "vera-agent") # 与 VERA_MCP_JWT_ISSUER 一致

def authorize(authz_header: str, expected_aud: str) -> dict | None:
    """用公钥验签；返回 claims 通过、None 表示拒绝（401）。"""
    if not authz_header.startswith("Bearer "):
        return None
    token = authz_header.removeprefix("Bearer ").strip()
    try:
        return jwt.decode(
            token, PUB,
            algorithms=["RS256"],
            audience=expected_aud,   # 必须 == 该 server 在 Vera 里的 name
            issuer=EXPECT_ISS,
        )
    except PyJWTError:
        return None   # 验签失败 / 过期 / aud 不符 → 拒绝
```

Node/TypeScript MCP server 用 `jsonwebtoken`：`jwt.verify(token, PUB, { algorithms: ["RS256"], audience, issuer })`。

#### (3) 在 Vera 前端配置这个 http MCP server

前端 → Agent → 工具配置 → 添加 MCP Server：

| 字段 | 值 | 说明 |
|------|-----|------|
| 名称 | `mysql-mcp` | **必须**与 server 侧验签时的 `audience` 一致（JWT `aud` 即取此值） |
| Transport | `streamable-http`（或 `http` / `sse`） | 选 HTTP 类才会注入 JWT |
| URL | 见下方说明 | **macOS 与 Linux 填法不同**，关键取决于容器怎么访问宿主机 |

> 📌 **如果先在 macOS 本地测试再部署到 Linux，注意 URL 要改**（`docker_client.py` 按平台自动选网络模式）：
>
> | 平台 | Docker 网络 | 容器访问宿主机的方式 | MCP URL 填 |
> |------|------------|---------------------|-----------|
> | **macOS** | `bridge`（Docker Desktop 无法 host 网络） | 走 Docker VM 内置 DNS `host.docker.internal` → 宿主机 | `http://host.docker.internal:3003/mcp` |
> | **Linux** | `host`（容器共享宿主机网络栈） | `127.0.0.1` **直接就是宿主机** | `http://127.0.0.1:3003/mcp` |
>
> `0.0.0.0` 是监听地址不是连接地址，**不要**填到 URL 里。

> **name ↔ audience 是硬耦合**：Vera 用 `name` 当 JWT 的 `aud`，server 侧必须用相同值校验，否则验签因 `aud` 不符而拒绝。

#### (4) 启动 http MCP server（示例）

```bash
# 以一个自带 JWT 验签中间件的 http MCP server 为例（独立后台进程）
cd /home/mysql-mcp
nohup env PORT=3003 JWT_PUBLIC_KEY_PATH=/home/mysql-mcp/mcp_jwt_public.pem \
    JWT_ISSUER=vera-agent node build/index.js --http > /var/log/mysql-mcp.log 2>&1 &
disown

# 验证端口起来了
sleep 1
curl -s http://127.0.0.1:3003/ | head -3
```

### 8.2 模型 B：stdio MCP + VERA_TOKEN 回调（无需 JWT）

内置 `vera-scheduler` 就是这种：agent 在容器内以子进程方式拉起它，后端自动把
`VERA_TOKEN`（用 `VERA_SESSION_SECRET` 签的 HMAC 会话 token）注入到它的 env。
该 server 回调 Vera REST API 时带上 `Authorization: Bearer $VERA_TOKEN` 即可，Vera 侧验签放行。

```python
# stdio MCP server 回调后端的写法
import os, urllib.request
token = os.environ["VERA_TOKEN"]
req = urllib.request.Request(
    f"{os.environ['VERA_BACKEND_URL']}/some/endpoint",
    headers={"Authorization": f"Bearer {token}"},
)
```

> 该模型始终开启，不需要任何额外配置；`VERA_SESSION_SECRET` 务必改成强随机值。

### 8.3 不需要鉴权的 http MCP（用 server 自身 API key）

以 FRED MCP Server 为例——它自己用 env 里的 `FRED_API_KEY` 鉴权，不依赖 Vera 的 JWT：

```bash
cd /home/fred-mcp-server-main
nohup env PORT=3003 FRED_API_KEY=你的key node build/index.js --http > /var/log/fred-mcp.log 2>&1 &
disown
sleep 1
curl -s http://127.0.0.1:3003/ | head -3
```

> ⚠️ 若全局 JWT 已开启，这个 server 也会收到一个 `Authorization: Bearer <jwt>` 头
> （见 8.1 的覆盖说明）。server 若不识别就忽略即可；若它严格只认 `FRED_API_KEY`，
> 需让 Vera 关掉 JWT，或改用 stdio 形态接它。

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
确保用了 `disown`（不只是 `nohup`），输出重定向到文件而非 tty。或直接上 systemd（第六节）。

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

### http/sse MCP 鉴权失败 / server 收不到 `Authorization` 头
按顺序排查：
1. **私钥是否填了**：`is_mcp_jwt_enabled()` 在私钥为空时**静默返回 False**，不会报错也不会注入 JWT。
   ```bash
   grep '^VERA_MCP_JWT_PRIVATE_KEY=' /home/vera-agent-main/backend/.env
   # 值非空、且是单行 \n 形式才算配置成功
   ```
2. **transport 是否选了 http 类**：只有 `http` / `sse` / `streamable-http` 才注入 JWT，`stdio` 不注入。
3. **改完 .env 必须重启后端**（systemd 或 nohup 都要），`lru_cache` 会缓存私钥。
4. **解码 JWT 看明文**（不验签，排查 `iss`/`aud`/`exp`）：
   ```bash
   echo "<jwt第二段>" | cut -d. -f2 | tr '_-' '/+' | base64 -d 2>/dev/null
   ```
5. **aud 是否对得上**：JWT 的 `aud` == 该 server 在 Vera 里的 `name` == server 侧验签声明的 `audience`，三者必须完全一致。

### JWT 会话中途失效（401 突然出现）
`VERA_MCP_JWT_TTL` 过短（默认 3600s）。把它调到 ≥ 单次会话最长时长后重启后端。

### agent 发现不了 MCP tools（tools 列表始终为空）

按顺序排查：

1. **URL 填错了**：`0.0.0.0` 是监听地址不能当连接地址，必须用 `127.0.0.1`；macOS 本地用 `host.docker.internal`（见 8.1(3) 表格）。
2. **MCP server 没启动**：`curl -s http://127.0.0.1:3003/ | head -3` 确认端口活着。
3. **JWT 私钥没配**：`grep VERA_MCP_JWT_PRIVATE_KEY .env` 值非空。
4. **改完 .env 没重启后端**：`pkill -f "uvicorn api.main"` 后重新启动。

### MCP server 侧 `RS256` 验签报错
- 确认 `mcp_jwt_public.pem` 是用 `openssl rsa -in 私钥 -pubout` 导出的、与 `.env` 里私钥配对的那把。
- `algorithms` 必须**显式传 `["RS256"]`**，不能省略或写 `none`。
- issuer / audience 与 Vera 侧一致（`VERA_MCP_JWT_ISSUER`、server 的 `name`）。
