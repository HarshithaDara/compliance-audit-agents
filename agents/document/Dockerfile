# Build from the repo root: docker build -f agents/document/Dockerfile -t audit-document .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
# OpenCV (used by RapidOCR) needs these shared libraries.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/document.txt
COPY common/ common/
COPY agents/__init__.py agents/
COPY agents/document/ agents/document/
# Load the OCR model once at build time so a broken install fails the build, not the first upload.
RUN python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()"
RUN useradd --uid 10001 --no-create-home agent
USER 10001
CMD ["python", "-m", "agents.document.agent"]
