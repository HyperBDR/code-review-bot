#!/bin/bash
# 可选：将 npm 安装的 opencode 替换为 baseline 版本（用于兼容性）
# 用法：./scripts/install-opencode-baseline.sh

set -e

OPENCODE_PATH=$(command -v opencode 2>/dev/null || true)
if [ -z "$OPENCODE_PATH" ]; then
  echo "错误：未找到 opencode，请先安装（npm install -g opencode-ai）"
  exit 1
fi

OPENCODE_DIR=$(dirname "$OPENCODE_PATH")
echo "找到 opencode: $OPENCODE_PATH"
echo "替换为 baseline 版本..."

cd "$(mktemp -d)"
curl -fsSL -o opencode-baseline.tar.gz \
  "https://github.com/anomalyco/opencode/releases/latest/download/opencode-linux-x64-baseline.tar.gz"
tar -xzf opencode-baseline.tar.gz

NEW_OPENCODE=$(find . -name "opencode" -type f 2>/dev/null | head -1)
if [ -z "$NEW_OPENCODE" ]; then
  echo "错误：解压后未找到 opencode 可执行文件"
  exit 1
fi

chmod +x "$NEW_OPENCODE"
mv "$OPENCODE_PATH" "${OPENCODE_PATH}.bak"
mv "$NEW_OPENCODE" "$OPENCODE_DIR/"
echo "完成：原 opencode 已备份为 ${OPENCODE_PATH}.bak"
