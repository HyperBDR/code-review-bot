#!/bin/sh
set -e

# Generate Claude Code settings.json from env for container deployments.
if [ -n "$CLAUDE_CODE_SETTINGS_CONTENT" ]; then
  mkdir -p /root/.claude
  chmod 700 /root/.claude
  echo "$CLAUDE_CODE_SETTINGS_CONTENT" > /root/.claude/settings.json
  chmod 600 /root/.claude/settings.json
  unset CLAUDE_CODE_SETTINGS_CONTENT
fi

exec "$@"
