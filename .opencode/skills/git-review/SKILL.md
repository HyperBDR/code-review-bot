---
name: git-review
description: 检查/拉取本地分支、本地 git diff、执行 AI 代码审查。支持 MR 模式和 push 模式。
compatibility: opencode
---

# Git Review

## 职责

对指定仓库的代码变更进行本地审查。支持两种模式：
- **MR 模式**：Merge Request，比较 source_branch 与 target_branch 的 diff
- **push 模式**：git push 触发，比较 before_sha 与 after_sha 的 diff

## 何时使用

- MR 模式：prompt 含 `repo_url`、`source_branch`、`target_branch`、`repo_workspace`、`project_path`
- push 模式：prompt 含 `repo_url`、`branch`、`before_sha`、`after_sha`、`repo_workspace`、`project_path`

## MR 模式工作流程

1. 确定本地仓库路径：`{repo_workspace}/{project_path}`
2. 若目录不存在：`git clone {repo_url} {repo_workspace}/{project_path}`
3. 进入目录：`cd {repo_workspace}/{project_path}`
4. 拉取分支：`git fetch origin {target_branch}` 和 `git fetch origin {source_branch}`
5. 获取 diff：`git diff origin/{target_branch}...origin/{source_branch}`
6. 代码审查并按规范格式输出结果

## push 模式工作流程

1. 确定本地仓库路径：`{repo_workspace}/{project_path}`
2. 若目录不存在：`git clone {repo_url} {repo_workspace}/{project_path}`
3. 进入目录：`cd {repo_workspace}/{project_path}`
4. 拉取分支：`git fetch origin {branch}` 或 `git fetch origin` 确保获取 before/after 的 commit
5. 获取 diff：`git diff {before_sha}..{after_sha}`（注意两点，表示区间）
6. 代码审查并按规范格式输出结果

## 输出格式

必须按以下结构输出，使用中文：

```markdown
## 审查总结
（一段话概括本次变更及整体评价）

## 发现的问题
- [严重] 问题描述...
- [建议] 问题描述...
（无问题时写：无）

## 建议
（可选，改进建议；无则省略）

## 结论
- **LGTM** / **需要修改**
```

- 问题分级：`[严重]` 表示必须修复，`[建议]` 表示可择机优化
- 结论必须二选一：**LGTM** 表示可接受，**需要修改** 表示有严重问题需处理

## 注意事项

- 确保 `repo_workspace` 目录已存在或有写权限
- 私有仓库需配置 git 凭证或使用带 token 的 URL
