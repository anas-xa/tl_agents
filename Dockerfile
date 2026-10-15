# One container, one port: builds the portal, then serves it from the API with demo data loaded.
FROM node:22-slim AS portal
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund --loglevel=error
COPY frontend/ ./
RUN npx vite build --logLevel error

FROM python:3.13-slim
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir -e .
COPY --from=portal /frontend/dist /app/frontend/dist
ENV QEONIX_SERVE_FRONTEND=true \
    QEONIX_SEED_DEMO_ON_START=true \
    QEONIX_STATIC_DIR=/app/frontend/dist \
    QEONIX_DATABASE_URL=sqlite:////data/qeonix.db \
    QEONIX_UPLOAD_DIR=/data/uploads \
    QEONIX_FRONTEND_BASE_URL=http://localhost:8000 \
    QEONIX_UAEPASS_ISSUER=http://localhost:8000/mock-uaepass \
    QEONIX_UAEPASS_REDIRECT_URI=http://localhost:8000/api/auth/callback
RUN mkdir -p /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
