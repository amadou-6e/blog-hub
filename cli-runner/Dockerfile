FROM python:3.12-slim

# System deps: Node (for provider CLIs) and browser prerequisites
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude CLI (Claude Code)
RUN npm install -g @anthropic-ai/claude-code

# OpenAI Codex CLI (browser device-code OAuth + coding agent)
RUN npm install -g @openai/codex

# Runner app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN patchright install --with-deps chromium
COPY main.py hashnode_browser.py medium_browser.py skyvern_browser.py browser_selectors.json ./

# Credential directories (will be overridden by named volumes in docker-compose)
RUN mkdir -p /root/.claude /root/.config/openai /data/skyvern-browser-sessions

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
