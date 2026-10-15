FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . 2>/dev/null || true
COPY . .
RUN pip install --no-cache-dir -e .
RUN mkdir -p /data
CMD ["sh", "-c", "python -m app.cli seed-demo && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
