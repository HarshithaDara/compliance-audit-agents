import os
import socket

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# One Redis stream per agent inbox. Agents talk only through these.
STREAM_CROSSCHECK = "audit:crosscheck"
STREAM_REGULATION = "audit:regulation"
STREAM_REPORT = "audit:report"
STREAM_EVENTS = "audit:events"
STREAM_DLQ = "audit:dlq"

MAX_DELIVERIES = int(os.getenv("MAX_DELIVERIES", "3"))
CLAIM_IDLE_MS = int(os.getenv("CLAIM_IDLE_MS", "60000"))
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", str(7 * 24 * 3600)))

CONSUMER_NAME = os.getenv("HOSTNAME") or socket.gethostname()

# SEC asks automated clients to declare who they are (https://www.sec.gov/os/accessing-edgar-data).
# Set this to "<your name or org> <your contact email>".
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "ComplianceAuditAgents research-project contact@example.com")

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
# auto: use Claude when ANTHROPIC_API_KEY is set, otherwise the deterministic template drafter.
LLM_MODE = os.getenv("LLM_MODE", "auto")

HEALTH_FILE = os.getenv("HEALTH_FILE", "/tmp/agent-healthy")

# Document audits (uploaded PDFs).
STREAM_DOCUMENT = "audit:document"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "64"))
DOC_BLOB_TTL_SECONDS = int(os.getenv("DOC_BLOB_TTL_SECONDS", "3600"))
# AI reader for documents. "local" talks to Ollama on this machine/cluster; nothing leaves it.
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
DOC_LLM_MAX_PAGES = int(os.getenv("DOC_LLM_MAX_PAGES", "40"))
DOC_OCR = os.getenv("DOC_OCR", "auto")  # auto | off
