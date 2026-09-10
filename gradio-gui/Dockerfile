# Build context is the repo root (see docker-compose.yml), for consistency
# with the other services, though this one has no local package dependency.
FROM python:3.11-slim

WORKDIR /app

COPY gradio-gui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gradio-gui/ .

CMD ["python", "app.py"]
