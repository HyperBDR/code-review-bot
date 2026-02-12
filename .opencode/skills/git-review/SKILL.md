---
name: git-review
description: 检查/拉取本地分支、本地 git diff、执行 AI 代码审查。支持 MR 模式和 push 模式。
compatibility: opencode
---

# Git Review

## 职责

对指定仓库的代码变更进行本地审查，且须兼顾「diff 本身」与「合入后整体代码逻辑」两方面：
- **diff 审查**：对变更内容逐行/逐文件做代码规范与正确性审查（含 Python 时使用 python-code-review skill；含 .vue 时使用 vue-code-review skill）
- **合入影响审查**：在获得 diff 后，结合仓库内相关代码（调用方、被调用方、配置、数据流等）评估本次合入是否与现有逻辑冲突、是否可能产生意外影响或破坏现有行为

支持两种模式：
- **MR 模式**：Merge Request，比较 source_branch 与 target_branch 的 diff
- **push 模式**：git push 触发，比较 before_sha 与 after_sha 的 diff

## 何时使用

- MR 模式：prompt 含 `repo_url`、`source_branch`、`target_branch`、`repo_workspace`、`project_path`
- push 模式：prompt 含 `repo_url`、`branch`、`before_sha`、`after_sha`、`repo_workspace`、`project_path`

## MR 模式工作流程

1. 确定本地仓库路径：`{repo_workspace}/{project_path}`
2. 若目录不存在：`git clone {repo_url} {repo_workspace}/{project_path}`；若已存在则进入目录后执行后续步骤
3. 进入目录：`cd {repo_workspace}/{project_path}`
4. 拉取分支：`git fetch origin {target_branch}` 和 `git fetch origin {source_branch}`
5. **切换到被审查分支**：`git checkout {source_branch}` 或 `git checkout -b {source_branch} origin/{source_branch}`。若切换失败（如有本地冲突、脏工作区等），则**删除该仓库目录**后重新执行从步骤 2 的 clone 开始，再 fetch 并 checkout
6. 获取 diff：`git diff origin/{target_branch}...origin/{source_branch}`
7. 代码审查：① 对 diff 做逐行/逐文件审查（若含 .py 须采用 **the-ai-engineer-python-code-review**；若含 .vue 须采用 **vue-code-review**）；② 结合仓库内相关文件评估合入后对整体逻辑的影响与风险（如调用关系、数据流、配置、边界行为）
8. 按规范格式输出结果（审查总结、发现的问题、建议、结论；合入影响可单独小节「整体影响与风险」或并入「发现的问题」）

## push 模式工作流程

1. 确定本地仓库路径：`{repo_workspace}/{project_path}`
2. 若目录不存在：`git clone {repo_url} {repo_workspace}/{project_path}`；若已存在则进入目录后执行后续步骤
3. 进入目录：`cd {repo_workspace}/{project_path}`
4. 拉取分支：`git fetch origin {branch}` 或 `git fetch origin` 确保获取 before/after 的 commit
5. **切换到本次 push 的分支**：`git checkout {branch}` 或 `git checkout -b {branch} origin/{branch}`。若切换失败（如有本地冲突、脏工作区等），则**删除该仓库目录**后重新执行从步骤 2 的 clone 开始，再 fetch 并 checkout
6. 获取 diff：`git diff {before_sha}..{after_sha}`（注意两点，表示区间）
7. 代码审查：① 对 diff 做逐行/逐文件审查（若含 .py 须采用 **the-ai-engineer-python-code-review**；若含 .vue 须采用 **vue-code-review**）；② 结合仓库内相关文件评估合入后对整体逻辑的影响与风险（如调用关系、数据流、配置、边界行为）
8. 按规范格式输出结果（审查总结、发现的问题、建议、结论；合入影响可单独小节「整体影响与风险」或并入「发现的问题」）

## 输出格式

必须按以下结构输出，使用中文：

```markdown
## 审查总结
（一段话概括本次变更及整体评价；可含合入后对整体逻辑的简要判断）

## 发现的问题
- [严重] 问题描述...
- [建议] 问题描述...
（无问题时写：无；若存在合入后整体影响类问题，在此或在下述「整体影响与风险」中列出）

## 整体影响与风险
（可选小节：从合入后整体代码逻辑角度，说明本次变更可能带来的影响、与现有逻辑的冲突或潜在风险；无则省略或写「无」）

## 建议
（可选，改进建议；无则省略）

## 结论
- **LGTM** / **需要修改**
```

- 问题分级：`[严重]` 表示必须修复，`[建议]` 表示可择机优化
- 结论必须二选一：**LGTM** 表示可接受，**需要修改** 表示有严重问题需处理

## 审查失败时的输出

若因任何原因无法完成审查（例如：clone/fetch 失败、checkout 失败或冲突、无法获取 diff、审查执行异常等），**必须明确输出失败原因**，便于调用方将原因回写到 GitLab（评论与 Commit 状态）。推荐格式：

```markdown
## 审查失败

**原因**：（简要说明失败原因，如：切换分支时发生冲突，已删库重拉仍失败；或：clone 超时；或：diff 为空/无法获取等）
```

输出后无需再输出「审查总结」「发现的问题」等正常小节；调用方会将该原因作为本次 review 的失败结果上报。

## 注意事项

- 确保 `repo_workspace` 目录已存在或有写权限
- 私有仓库需配置 git 凭证或使用带 token 的 URL
- **切换分支**：审查前必须先切换到被审查分支（MR 为 source_branch，push 为 branch）；若 checkout 因冲突或脏工作区失败，则删除 `{repo_workspace}/{project_path}` 后重新 clone 并 fetch、checkout
- **失败上报**：任何步骤失败导致无法完成审查时，必须按「审查失败时的输出」格式输出原因，以便调用方将原因回写到 GitLab
- **Python 审查**：变更中含 `.py` 文件时，必须使用 **the-ai-engineer-python-code-review**（python-code-review）skill 的标准执行审查，输出格式仍按本 skill 的「输出格式」用中文呈现
- **Vue 审查**：变更中含 `.vue` 文件时，必须使用 **vue-code-review** skill 的标准执行审查，输出格式仍按本 skill 的「输出格式」用中文呈现
