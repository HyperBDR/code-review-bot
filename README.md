# code-review-bot

轻量级 GitLab AI 代码审查服务。通过 Webhook 触发 **Merge Request** / **Push** 事件，调用 [OpenCode](https://opencode.ai/) 与 git-review skill 完成代码审查，并将结果回传至 GitLab。

- **本地**：需安装 OpenCode CLI 且已认证
- **Docker**：镜像内置 OpenCode，通过 `OPENCODE_CONFIG_CONTENT` 传入配置（entrypoint 写入 opencode.json）

---

## 功能

| 功能 | 说明 |
|------|------|
| MR 审查 | Merge Request 创建/更新时，对 source vs target 分支 diff 进行 AI 审查，评论到 MR |
| Push 审查 | git push 时，对 before_sha..after_sha 区间变更进行 AI 审查，评论到对应 commit |
| Commit 状态 | 设置 `code-review-bot` 为 running → success/failed，可与合并门禁配合 |
| 审查格式 | 审查总结、发现的问题、建议、结论（LGTM / 需要修改） |

```
GitLab (MR/Push) → POST /webhook → FastAPI → opencode run → git-review → 评论+状态回传 GitLab
```

---

## 快速开始

### 1. Docker Compose（推荐）

```bash
cd code-review-bot
cp .env.example .env
# 编辑 .env，至少填写 GITLAB_TOKEN、GITLAB_URL、OPENCODE_CONFIG_CONTENT

docker compose up -d
docker compose logs -f
```

挂载：`./repos`（仓库缓存）、`./logs`（运行日志）

### 2. 本地运行

```bash
cd code-review-bot
uv sync
cp .env.example .env
# 编辑 .env，并创建 ~/.config/opencode/opencode.json

uv run uvicorn app.main:app --host 0.0.0.0 --port 5000
```

**环境**：Python 3.10+、[uv](https://docs.astral.sh/uv/)、OpenCode CLI（已认证）、git

### 3. docker run

```bash
docker build -t code-review-bot:latest .

docker run -d \
  --name code-review-bot \
  --restart unless-stopped \
  -p 5000:5000 \
  -e GITLAB_URL=http://your-gitlab.example.com \
  -e GITLAB_TOKEN=glpat-xxxxxxxxxxxx \
  -e OPENCODE_CONFIG_CONTENT='{"$schema":"https://opencode.ai/config.json","provider":{"agione":{"npm":"@ai-sdk/openai-compatible","name":"agione","options":{"baseURL":"https://zh.agione.co/hyperone/xapi/api","apiKey":"ak-xxx"},"models":{"131249505071992832":{"name":"GLM-4"}}}}' \
  -e OPENCODE_MODEL=agione/131249505071992832 \
  -v $(pwd)/repos:/app/repos \
  -v $(pwd)/logs:/app/logs \
  code-review-bot:latest
```

### 4. GitLab Webhook

1. 项目 → **Settings** → **Webhooks**
2. **URL**：`http://<服务地址>:5000/webhook`
3. **Trigger**：勾选 **Merge request events**、**Push events**

### 5. 验证

```bash
curl http://localhost:5000/health   # 返回 {"status":"ok"}
```

Push/MR 触发后，评论区出现 🤖 **Code Review Result**

---

## 配置

复制 `.env.example` 为 `.env` 后编辑。配置通过环境变量传入。

### 环境变量

| 变量 | 必需 | 默认 | 说明 |
|------|:----:|------|------|
| `GITLAB_TOKEN` | ✓ | - | Personal Access Token，需 `api` scope |
| `OPENCODE_CONFIG_CONTENT` | ✓(Docker) | - | 完整 opencode.json 单行 JSON |
| `GITLAB_URL` | | `http://localhost` | GitLab 地址 |
| `REPO_WORKSPACE` | | `repos` | 仓库缓存（Docker 内为 /app/repos） |
| `OPENCODE_CMD` | | `opencode` | opencode 命令 |
| `OPENCODE_LOG_LEVEL` | | `WARN` | opencode 日志级别 |
| `OPENCODE_MODEL` | | - | 模型，格式 `provider/model` |
| `HOST` | | `0.0.0.0` | 监听地址 |
| `PORT` | | `5000` | 监听端口 |
| `REVIEW_TIMEOUT` | | `600` | 审查超时（秒） |
| `API_TIMEOUT` | | `10` | GitLab API 超时（秒） |
| `LOG_FILE` | | 空 | 日志文件路径（Docker Compose 默认 /app/logs/app.log） |

### OPENCODE_CONFIG_CONTENT 示例

Docker 启动时 entrypoint 会将其写入 `/root/.config/opencode/opencode.json`。支持任意 provider，apiKey 直接写在 JSON 中，或使用 `{env:变量名}` 引用环境变量。

**agione：**

```bash
OPENCODE_CONFIG_CONTENT='{"$schema":"https://opencode.ai/config.json","provider":{"agione":{"npm":"@ai-sdk/openai-compatible","name":"agione","options":{"baseURL":"https://zh.agione.co/hyperone/xapi/api","apiKey":"ak-你的Key"},"models":{"131249505071992832":{"name":"GLM-4"}}}}'
OPENCODE_MODEL=agione/131249505071992832
```

**OpenAI：**

```bash
OPENCODE_CONFIG_CONTENT='{"$schema":"https://opencode.ai/config.json","model":"openai/gpt-4o","provider":{"openai":{"options":{"apiKey":"sk-xxx"}}}}'
```

> 注意：JSON 中模型 ID 的 key 必须加引号，如 `"131249505071992832"`。

---

## 审查结果格式

| 章节 | 说明 |
|------|------|
| 审查总结 | 概括本次变更及整体评价 |
| 发现的问题 | `[严重]` 必须修复，`[建议]` 可择机优化 |
| 建议 | 改进建议 |
| 结论 | **LGTM** 或 **需要修改** |

---

## 项目结构

```
code-review-bot/
├── app/
│   ├── main.py              # 入口
│   ├── config.py            # 配置
│   ├── routers/webhook.py   # /webhook、/health
│   └── services/
│       ├── webhook.py       # Push/MR 业务逻辑
│       ├── opencode.py      # opencode 调用
│       └── gitlab.py        # GitLab API
├── .opencode/skills/git-review/
├── scripts/
│   ├── entrypoint.sh        # Docker 生成 opencode.json
│   └── install-opencode-baseline.sh
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── uv.lock
```

---

## 常见问题

**GitLab API 403**  
Token 需 `api` scope。

**git-review skill 未找到**  
从项目根目录启动，或：`cp -r .opencode/skills/git-review ~/.config/opencode/skills/`

**审查超时**  
调大 `REVIEW_TIMEOUT`（如 900）。

**Docker 内 opencode 未认证**  
确保 `OPENCODE_CONFIG_CONTENT` 含完整配置且 apiKey 正确。JSON 中模型 ID 需加引号。

**OpenCode baseline 版本**  
Docker 默认使用 baseline。用 npm 版：`USE_OPENCODE_BASELINE=false`。本地替换：`./scripts/install-opencode-baseline.sh`。
