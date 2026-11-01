# Control plane image. Build context is the repo root (ai-platform/), like every
# other service — see docker-compose.yml. It holds the Docker socket at runtime, so
# it runs as a non-root user that is only granted the host's docker group via
# compose `group_add`.
FROM python:3.12-slim

WORKDIR /app

# Override where PyPI is unreachable, e.g. --build-arg PIP_INDEX_URL=https://package-mirror.liara.ir/repository/pypi/simple
ARG PIP_INDEX_URL=https://pypi.org/simple

COPY code-sandbox-service/requirements.txt .
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY code-sandbox-service/ .
RUN chmod +x entrypoint.sh \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin sandboxctl

USER 10001

CMD ["./entrypoint.sh"]
