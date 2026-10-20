# Build from the repo root: docker build -f agents/reporter/Dockerfile -t audit-reporter .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/reporter.txt
COPY common/ common/
COPY agents/__init__.py agents/
COPY agents/reporter/ agents/reporter/
RUN useradd --uid 10001 --no-create-home agent
USER 10001
CMD ["python", "-m", "agents.reporter.agent"]
