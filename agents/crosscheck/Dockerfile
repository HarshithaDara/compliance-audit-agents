# Build from the repo root: docker build -f agents/crosscheck/Dockerfile -t audit-crosscheck .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/crosscheck.txt
COPY common/ common/
COPY agents/__init__.py agents/
COPY agents/crosscheck/ agents/crosscheck/
RUN useradd --uid 10001 --no-create-home agent
USER 10001
CMD ["python", "-m", "agents.crosscheck.agent"]
