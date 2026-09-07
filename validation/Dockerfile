FROM python:3.12.8-slim-bookworm@sha256:2199a62885a12290dc9c5be3ca0681d367576ab7bf037da120e564723292a2f0
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libnss3-tools && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY validation/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock && playwright install --with-deps chromium && patchright install chromium
COPY . /app
ENV PYTHONPATH=/app:/app/cli-runner PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["sh", "/app/validation/trust.sh"]
