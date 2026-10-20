import fakeredis
import pytest

from agents.crosscheck import sec_client
from agents.crosscheck.sec_client import SecClient, SecNotFound


@pytest.fixture
def offline(monkeypatch):
    def no_network(*a, **kw):
        raise AssertionError("network call made despite seeded cache")
    monkeypatch.setattr(sec_client.requests, "get", no_network)


def test_seeded_cache_is_served_without_network(offline):
    r = fakeredis.FakeRedis(decode_responses=True)
    sec = SecClient(r)
    sec.seed_tickers({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})
    sec.seed_facts("0000320193", {"entityName": "Apple Inc.", "facts": {}})
    sec.seed_submissions("0000320193", {"sic": "3571", "sicDescription": "Electronic Computers"})

    assert sec.lookup_cik("aapl") == ("0000320193", "Apple Inc.")
    assert sec.company_facts("0000320193")["entityName"] == "Apple Inc."
    assert sec.sic("0000320193") == ("3571", "Electronic Computers")
    with pytest.raises(SecNotFound):
        sec.lookup_cik("ZZZZZQ")
