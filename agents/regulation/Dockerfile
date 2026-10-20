# Build from the repo root: docker build -f agents/regulation/Dockerfile -t audit-regulation .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app \
    FASTEMBED_CACHE=/models REG_INDEX_DIR=/app/index REG_INDEX_DIR_IN=/app/index_in \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1
WORKDIR /app
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/regulation.txt
COPY common/ common/
COPY agents/__init__.py agents/
COPY agents/regulation/ agents/regulation/
COPY data/regulations.jsonl data/regulations_in.jsonl data/
# Bake the embedding model and both BM25/dense indexes (SEC, Indian tax) into the image, so pods start
# without network access and every replica serves an identical index.
RUN python -m agents.regulation.retriever && chmod -R a+rX /models /app/index /app/index_in
RUN useradd --uid 10001 --no-create-home agent
USER 10001
CMD ["python", "-m", "agents.regulation.agent"]
