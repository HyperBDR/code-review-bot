# Code Review Bot

服务端用于**响应 GitLab 的 Webhook 通知**：基于 **Skills** 的代码审查工具，收到 MR/Push 事件后调用 [OpenCode](https://opencode.ai/) 与 **git-review** skill 执行审查，并将结果写回 GitLab（MR 评论 / Commit 状态）。

- **本地**：需安装 OpenCode CLI 并完成认证
- **Docker**：镜像内置 OpenCode，用 `OPENCODE_CONFIG_CONTENT` 传入配置（entrypoint 写入 opencode.json）

---

## 功能

| 功能 | 说明 |
|------|------|
| MR 审查 | MR 创建/更新时对 source vs target diff 做审查，评论到 MR |
| Push 审查 | Push 时对 before_sha..after_sha 变更做审查，评论到对应 commit |
| Commit 状态 | 设置 `code-review-bot` 为 running → success/failed，可作合并门禁 |
| 审查格式 | 总结、问题（严重/建议）、建议、结论（LGTM / 需要修改） |

```
GitLab (MR/Push) → POST /webhook → FastAPI → opencode run + git-review skill → 评论/状态回写 GitLab
```

---

## 部署

### 环境变量

生产与开发均需先配置环境变量。`cp .env.example .env` 后按需编辑。

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

**OPENCODE_CONFIG_CONTENT 示例**

Docker 下 entrypoint 会写入 `/root/.config/opencode/opencode.json`。支持任意 provider，apiKey 可写死在 JSON 或用 `{env:变量名}` 引用。

```bash
# agione
OPENCODE_CONFIG_CONTENT='{"$schema":"https://opencode.ai/config.json","provider":{"agione":{"npm":"@ai-sdk/openai-compatible","name":"agione","options":{"baseURL":"https://zh.agione.co/hyperone/xapi/api","apiKey":"ak-你的Key"},"models":{"131249505071992832":{"name":"GLM-4"}}}}}'
OPENCODE_MODEL=agione/131249505071992832
```

```bash
# OpenAI
OPENCODE_CONFIG_CONTENT='{"$schema":"https://opencode.ai/config.json","model":"openai/gpt-4o","provider":{"openai":{"options":{"apiKey":"sk-xxx"}}}}'
```

> 注意：JSON 中模型 ID 的 key 必须加引号，如 `"131249505071992832"`。

### 生产环境

使用 Docker Compose，环境变量见上一节。

```bash
cd code-review-bot
# At least set GITLAB_TOKEN, GITLAB_URL, OPENCODE_CONFIG_CONTENT
cp .env.example .env
docker compose up -d
docker compose logs -f
```

挂载：`./repos`（仓库缓存）、`./logs`（日志）

### 开发环境

环境变量与生产一致，见 [环境变量](#环境变量)。另需本机安装 OpenCode CLI 并配置 `~/.config/opencode/opencode.json`。

**依赖**：Python 3.10+、[uv](https://docs.astral.sh/uv/)、OpenCode CLI（已认证）、git

```bash
cd code-review-bot
uv sync
# Also configure ~/.config/opencode/opencode.json
cp .env.example .env
uv run uvicorn app.main:app --host 0.0.0.0 --port 5000
```

---

## Webhook 配置

1. GitLab 项目 **Settings** → **Webhooks**
2. **URL**：`http://<服务地址>:5000/webhook`
3. **Trigger**：勾选 **Merge request events**、**Push events**

**验证**

```bash
# Expected response: {"status":"ok"}
curl http://localhost:5000/health
```

配置正确且服务运行后，触发 MR/Push，评论区可见 🤖 **Code Review Result**。

---

## 审查结果

| 章节 | 说明 |
|------|------|
| 审查总结 | 变更概览与整体评价 |
| 发现的问题 | `[严重]` 必修，`[建议]` 可选 |
| 建议 | 改进建议 |
| 结论 | **LGTM** 或 **需要修改** |

---

## 开发文档

### 代码结构

```
code-review-bot/
├── app/
│   ├── main.py                 # entry
│   ├── config.py               # config
│   ├── routers/webhook.py      # /webhook, /health
│   └── services/
│       ├── webhook.py          # Push/MR flow
│       ├── opencode.py         # OpenCode invoke
│       └── gitlab.py           # GitLab API
├── .opencode/skills/
│   ├── git-review/                  # review flow (clone, diff)
│   └── the-ai-engineer-python-code-review/   # Python review (PEP 8 + Google)
├── scripts/
│   ├── entrypoint.sh           # Docker: write opencode.json
│   └── install-opencode-baseline.sh
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── uv.lock
```

### 常见问题

| 现象 | 处理 |
|------|------|
| GitLab API 403 | Token 需 `api` scope |
| git-review skill 未找到 | 从项目根启动，或 `cp -r .opencode/skills/git-review ~/.config/opencode/skills/` |
| 审查超时 | 调大 `REVIEW_TIMEOUT`（如 900） |
| Docker 内 opencode 未认证 | 确认 `OPENCODE_CONFIG_CONTENT` 完整、apiKey 正确，模型 ID 加引号 |
| 使用 npm 版 OpenCode | Docker：`USE_OPENCODE_BASELINE=false`；本地：`./scripts/install-opencode-baseline.sh` |

### 代码规范

- **注释写在行上方**：不使用行内注释，注释单独占行写在对应代码上方（含 README 等文档中的代码块），与项目代码风格一致。
- **代码内注释使用英文**：便于协作与工具链兼容。
