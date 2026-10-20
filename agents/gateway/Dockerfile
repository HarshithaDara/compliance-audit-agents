# Build from the repo root: docker build -f agents/gateway/Dockerfile -t audit-gateway .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/gateway.txt
COPY common/ common/
COPY agents/__init__.py agents/
COPY agents/gateway/ agents/gateway/
RUN useradd --uid 10001 --no-create-home agent
USER 10001
EXPOSE 8000
CMD ["uvicorn", "agents.gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
