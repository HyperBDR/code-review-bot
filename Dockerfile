# code-review-bot
# Ubuntu 24.04 + Python 3 + Node.js (for Claude Code CLI)
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    curl \
    wget \
    git \
    ca-certificates \
    vim \
    iputils-ping \
    dnsutils \
    net-tools \
    traceroute \
    && rm -rf /var/lib/apt/lists/*

# uv 与 uvicorn 需要 python 命令
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3 1

# Install Node.js 20.x
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Install uv (standalone installer)
ENV PATH="/root/.local/bin:$PATH"
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app

# Python dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Application
COPY app/ ./app/
COPY claude-skills/ ./claude-skills/
COPY scripts/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh && mkdir -p repos

EXPOSE 5000

ENV REPO_WORKSPACE=/app/repos

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000"]
