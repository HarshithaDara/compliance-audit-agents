"""Redis Streams message bus shared by all agents.

Each agent role owns one inbox stream and one consumer group; every pod of that role
is a consumer in the group, so scaling a Deployment spreads work across replicas.
Messages are acked only after the handler succeeds. Messages left pending by a crashed
pod are reclaimed with XAUTOCLAIM, and after MAX_DELIVERIES attempts go to the DLQ.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable

import redis

from common import config
from common.schemas import AuditMessage

log = logging.getLogger("bus")

Handler = Callable[[AuditMessage], None]


def connect(url: str | None = None) -> redis.Redis:
    # socket_timeout must exceed the XREADGROUP block time, or blocking reads time out.
    return redis.Redis.from_url(url or config.REDIS_URL, decode_responses=True, socket_timeout=30,
                                socket_connect_timeout=5, socket_keepalive=True, health_check_interval=30,
                                retry_on_timeout=True)


def job_key(job_id: str) -> str:
    return f"audit:job:{job_id}"


def publish(r: redis.Redis, stream: str, msg: AuditMessage) -> str:
    return r.xadd(stream, {"data": msg.model_dump_json()}, maxlen=10000, approximate=True)


TERMINAL = {"completed", "failed"}


def set_status(r: redis.Redis, job_id: str, status: str, **fields) -> bool:
    """Atomically update job status. A job that reached a terminal state is never moved back,
    so a slow agent's late progress update can't overwrite another agent's 'completed'."""
    key = job_key(job_id)
    extra = {k: str(v) for k, v in fields.items()}
    mapping = {"status": status, "updated_at": f"{time.time():.3f}", **extra}

    def txn(pipe: redis.client.Pipeline) -> bool:
        if pipe.hget(key, "status") in TERMINAL:
            return False
        pipe.multi()
        pipe.hset(key, mapping=mapping)
        pipe.expire(key, config.JOB_TTL_SECONDS)
        return True

    updated = r.transaction(txn, key, value_from_callable=True)
    if updated:
        r.xadd(config.STREAM_EVENTS, {"job_id": job_id, "status": status, **extra}, maxlen=10000, approximate=True)
    return updated


def ensure_group(r: redis.Redis, stream: str, group: str) -> None:
    try:
        r.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def _touch_health() -> None:
    try:
        with open(config.HEALTH_FILE, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


class Worker:
    """Consumer-group worker loop for one agent role."""

    def __init__(self, r: redis.Redis, stream: str, group: str, handler: Handler,
                 consumer: str | None = None, block_ms: int = 5000):
        self.r = r
        self.stream = stream
        self.group = group
        self.handler = handler
        self.consumer = consumer or config.CONSUMER_NAME
        self.block_ms = block_ms
        ensure_group(r, stream, group)

    def _deliveries(self, msg_id: str) -> int:
        info = self.r.xpending_range(self.stream, self.group, min=msg_id, max=msg_id, count=1)
        return int(info[0]["times_delivered"]) if info else 1

    def _handle(self, msg_id: str, fields: dict) -> None:
        try:
            msg = AuditMessage.model_validate_json(fields["data"])
        except Exception:
            log.exception("malformed message %s, sending to DLQ", msg_id)
            self.r.xadd(config.STREAM_DLQ, {"stream": self.stream, "data": json.dumps(fields), "error": "malformed"})
            self.r.xack(self.stream, self.group, msg_id)
            return
        try:
            self.handler(msg)
            self.r.xack(self.stream, self.group, msg_id)
        except Exception as e:
            deliveries = self._deliveries(msg_id)
            log.exception("job %s failed in %s (delivery %d)", msg.job_id, self.group, deliveries)
            if deliveries >= config.MAX_DELIVERIES:
                self.r.xadd(config.STREAM_DLQ, {"stream": self.stream, "data": fields["data"], "error": repr(e)})
                set_status(self.r, msg.job_id, "failed", failed_in=self.group, error=repr(e)[:500])
                self.r.xack(self.stream, self.group, msg_id)
            # otherwise leave it pending; it is retried via XAUTOCLAIM after CLAIM_IDLE_MS

    def poll_once(self) -> int:
        """Process at most one batch. Returns the number of messages handled."""
        _touch_health()
        handled = 0
        # Reclaim messages stuck with dead or failed consumers first.
        claimed = self.r.xautoclaim(self.stream, self.group, self.consumer,
                                    min_idle_time=config.CLAIM_IDLE_MS, start_id="0-0", count=10)
        for msg_id, fields in claimed[1]:
            if fields:
                self._handle(msg_id, fields)
                handled += 1
        resp = self.r.xreadgroup(self.group, self.consumer, {self.stream: ">"}, count=1, block=self.block_ms)
        for _stream, entries in resp or []:
            for msg_id, fields in entries:
                self._handle(msg_id, fields)
                handled += 1
        return handled

    def run_forever(self) -> None:
        log.info("%s consuming %s as %s", self.group, self.stream, self.consumer)
        while True:
            try:
                self.poll_once()
            except (redis.ConnectionError, redis.TimeoutError) as e:
                log.warning("redis unavailable (%s), retrying in 2s", e)
                time.sleep(2)


def setup_logging() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
