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
