"""Multi-agent pipeline over a (fake) Redis: gateway -> crosscheck -> regulation -> reporter,
including the reporter->regulation refinement loop, retries and the dead-letter queue."""
import fakeredis
import pytest
from fastapi.testclient import TestClient

from agents.crosscheck import agent as crosscheck_agent
from agents.crosscheck.sec_client import SecNotFound
from agents.gateway import app as gateway
from agents.regulation import agent as regulation_agent
from agents.regulation.retriever import INDEX_DIR, Hit, Retriever
from agents.reporter import agent as reporter_agent
from agents.reporter.drafter import TemplateDrafter
from common import bus, config
from tests import factories


class FakeSec:
    def __init__(self, facts):
        self.facts = facts
        self.calls = 0

    def lookup_cik(self, ticker):
        if ticker == "NOPE":
            raise RuntimeError("SEC temporarily unavailable")
        if ticker == "GONE":
            raise SecNotFound("unknown ticker GONE")
        return "0000000001", "Synthetic Corp"

    def company_facts(self, cik):
        self.calls += 1
        return self.facts

    def sic(self, cik):
        return "3571", "Electronic Computers"


@pytest.fixture(scope="module")
def retriever():
    return Retriever(INDEX_DIR, mode="bm25")


@pytest.fixture
def env(retriever, monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(gateway, "_redis", r)
    monkeypatch.setattr(config, "CLAIM_IDLE_MS", 0)
    v = factories.healthy_values()
    v["Revenues"] = ("USD", True, 800e6, 600e6)     # triggers a YOY_REVENUE warning
    sec = FakeSec(factories.build(values=v))
    workers = [
        bus.Worker(r, config.STREAM_CROSSCHECK, "crosscheck", crosscheck_agent.make_handler(r, sec), "cc-0", 10),
        bus.Worker(r, config.STREAM_REGULATION, "regulation", regulation_agent.make_handler(r, retriever), "rg-0", 10),
        bus.Worker(r, config.STREAM_REPORT, "reporter", reporter_agent.make_handler(r, TemplateDrafter()), "rp-0", 10),
    ]

    def drain(max_rounds=20):
        for _ in range(max_rounds):
            if sum(w.poll_once() for w in workers) == 0:
                return
    return SimpleEnv(r, TestClient(gateway.app), workers, drain, sec)


class SimpleEnv:
    def __init__(self, r, client, workers, drain, sec):
        self.r, self.client, self.workers, self.drain, self.sec = r, client, workers, drain, sec


def test_end_to_end_job_completes(env):
    job = env.client.post("/audits", json={"ticker": "syn"}).json()
    env.drain()
    state = env.client.get(f"/audits/{job['job_id']}").json()
    assert state["status"] == "completed", state
    assert state["summary"]["flagged"] == ["YOY_REVENUE"]
    report = env.client.get(f"/audits/{job['job_id']}/report").text
    assert "Synthetic Corp (SYN)" in report and "17 CFR 229.303" in report
    result = env.client.get(f"/audits/{job['job_id']}/result").json()
    assert [t["agent"] for t in result["trace"]] == ["gateway", "crosscheck", "regulation", "reporter"]
    q = env.client.get("/queues").json()
    assert all(v.get("pending", 0) == 0 and v.get("lag", 0) == 0 for v in q.values())


def test_reporter_requests_refinement_for_weak_citations(env, monkeypatch, retriever):
    real_search = retriever.search

    def weak_first(query, k=3, candidates=40, industry="general"):
        hits = real_search(query, k, candidates, industry)
        if candidates == 40:  # first pass: pretend nothing relevant was found
            return [Hit(**{**h.__dict__, "score": 0.1}) for h in hits]
        return hits
    monkeypatch.setattr(retriever, "search", weak_first)
    job = env.client.post("/audits", json={"ticker": "SYN"}).json()
    env.drain()
    result = env.client.get(f"/audits/{job['job_id']}/result").json()
    agents = [t["agent"] for t in result["trace"]]
    assert agents == ["gateway", "crosscheck", "regulation", "reporter", "regulation", "reporter"]
    assert result["refinement_round"] == 1
    yoy = next(f for f in result["findings"] if f["check_id"] == "YOY_REVENUE")
    assert max(c["score"] for c in yoy["citations"]) >= reporter_agent.MIN_CITATION_SCORE


def test_bad_fiscal_year_fails_fast(env):
    job = env.client.post("/audits", json={"ticker": "SYN", "fiscal_year": 2012}).json()
    env.drain()
    state = env.client.get(f"/audits/{job['job_id']}").json()
    assert state["status"] == "failed" and "fiscal year 2012" in state["error"]


def test_unknown_ticker_fails_fast_without_retry(env):
    job = env.client.post("/audits", json={"ticker": "GONE"}).json()
    env.workers[0].poll_once()
    state = env.client.get(f"/audits/{job['job_id']}").json()
    assert state["status"] == "failed" and "unknown ticker" in state["error"]
    assert env.r.xlen(config.STREAM_DLQ) == 0


def test_repeated_failures_go_to_dead_letter_queue(env):
    job = env.client.post("/audits", json={"ticker": "NOPE"}).json()
    for _ in range(config.MAX_DELIVERIES + 1):
        env.workers[0].poll_once()
    state = env.client.get(f"/audits/{job['job_id']}").json()
    assert state["status"] == "failed" and state["failed_in"] == "crosscheck"
    assert env.r.xlen(config.STREAM_DLQ) == 1


def test_malformed_message_is_dead_lettered(env):
    env.r.xadd(config.STREAM_CROSSCHECK, {"data": "{not json"})
    env.workers[0].poll_once()
    assert env.r.xlen(config.STREAM_DLQ) == 1


def test_terminal_status_is_never_overwritten(env):
    """Regression: a late progress update from an upstream agent must not undo 'completed'."""
    assert bus.set_status(env.r, "j1", "drafting_report")
    assert bus.set_status(env.r, "j1", "completed", summary="{}")
    assert not bus.set_status(env.r, "j1", "drafting_report")
    assert env.r.hget(bus.job_key("j1"), "status") == "completed"


class FlakyRedis(fakeredis.FakeRedis):
    """Refuses connections for the first N commands, like Redis still starting up."""

    def __init__(self, *a, down_for=2, **kw):
        super().__init__(*a, **kw)
        self.down_for = down_for

    def execute_command(self, *args, **kw):
        if self.down_for > 0:
            self.down_for -= 1
            import redis
            raise redis.ConnectionError("Connection refused")
        return super().execute_command(*args, **kw)


def test_worker_waits_for_redis_at_startup(monkeypatch):
    """Regression: agent pods crashed on cold start because Redis wasn't accepting connections yet."""
    monkeypatch.setattr(bus.time, "sleep", lambda s: None)
    r = FlakyRedis(decode_responses=True, down_for=2)
    w = bus.Worker(r, "audit:test", "testers", lambda m: None, "t-0", 10)
    assert w.r.xinfo_groups("audit:test")[0]["name"] == "testers"


def test_worker_heartbeats_while_waiting_for_redis(monkeypatch, tmp_path):
    """Regression: k8s liveness killed agents that were waiting for Redis at startup, because the
    heartbeat file was only touched while polling. Waiting is alive; a restart can't fix it."""
    health = tmp_path / "healthy"
    monkeypatch.setattr(config, "HEALTH_FILE", str(health))
    beats = []
    monkeypatch.setattr(bus.time, "sleep", lambda s: beats.append(health.exists()))
    bus.Worker(FlakyRedis(decode_responses=True, down_for=3), "audit:test", "testers", lambda m: None, "t-0", 10)
    assert beats == [True, True, True]


def test_worker_recreates_lost_consumer_group(env):
    """If Redis loses the stream/group (e.g. restart without persistence), polling recovers."""
    worker = env.workers[0]
    env.r.delete(config.STREAM_CROSSCHECK)
    worker.poll_once()  # must not raise NOGROUP
    job = env.client.post("/audits", json={"ticker": "SYN"}).json()
    env.drain()
    assert env.client.get(f"/audits/{job['job_id']}").json()["status"] == "completed"


def test_liveness_does_not_depend_on_redis(env, monkeypatch):
    """Regression: the gateway's liveness probe pinged Redis, so a Redis outage made k8s restart a healthy
    gateway. Liveness must reflect only the process; readiness reports the dependency."""
    import redis

    def down():
        raise redis.ConnectionError("Connection refused")
    monkeypatch.setattr(env.r, "ping", down)
    assert env.client.get("/livez").status_code == 200
    assert env.client.get("/healthz").status_code == 503


def test_queues_count_only_live_consumers(env, monkeypatch):
    """Regression: after scaling crosscheck 4 -> 2, /queues still reported 4 workers because Redis
    keeps consumers of deleted pods registered. Live workers re-poll every few seconds."""
    real = env.r.xinfo_consumers

    def consumers(stream, group):
        if stream == config.STREAM_CROSSCHECK:
            return [{"name": "live-a", "idle": 900}, {"name": "live-b", "idle": 4000},
                    {"name": "gone-c", "idle": 600000}, {"name": "gone-d", "idle": 90000}]
        return real(stream, group)
    monkeypatch.setattr(env.r, "xinfo_consumers", consumers)
    assert env.client.get("/queues").json()[config.STREAM_CROSSCHECK]["consumers"] == 2


def test_web_ui_is_served_at_root(env):
    res = env.client.get("/")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/html")
    assert "<title>Compliance Audit Agents</title>" in res.text
    # the page only calls endpoints that exist
    for path in ("/audits", "/queues", "/documents"):
        assert f'"{path}' in res.text or f"`{path}" in res.text


def test_gateway_validates_input(env):
    assert env.client.post("/audits", json={"ticker": "AAPL; DROP"}).status_code == 422
    assert env.client.post("/audits", json={"ticker": "AAPL", "fiscal_year": 1990}).status_code == 422
    assert env.client.get("/audits/doesnotexist").status_code == 404
