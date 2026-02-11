#!/bin/sh
set -e

# 根据 OPENCODE_CONFIG_CONTENT 生成 opencode.json（OpenCode 不读取该环境变量，需写入文件）
if [ -n "$OPENCODE_CONFIG_CONTENT" ]; then
  mkdir -p /root/.config/opencode
  echo "$OPENCODE_CONFIG_CONTENT" > /root/.config/opencode/opencode.json
fi

exec "$@"
