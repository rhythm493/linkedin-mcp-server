"""Tests for the persistent SQLite-backed job cache."""

from typing import Any

import pytest

from linkedin_mcp_server.tools._job_cache import JobCache


SAMPLE_RESULT: dict[str, Any] = {
    "url": "https://www.linkedin.com/jobs/view/123/",
    "sections": {"job_posting": "Senior Engineer at Google\nSan Francisco"},
    "job_id": "123",
}


@pytest.fixture
def cache(tmp_path):
    return JobCache(tmp_path / "job-cache.db")


class TestJobCache:
    def test_roundtrip(self, cache):
        cache.set("123", SAMPLE_RESULT)
        got = cache.get("123")
        assert got is not None
        assert got["url"] == SAMPLE_RESULT["url"]
        assert (
            got["sections"]["job_posting"] == SAMPLE_RESULT["sections"]["job_posting"]
        )
        assert got["job_id"] == "123"

    def test_miss_returns_none(self, cache):
        assert cache.get("nonexistent") is None

    def test_overwrite_existing(self, cache):
        cache.set("123", SAMPLE_RESULT)
        updated = {**SAMPLE_RESULT, "sections": {"job_posting": "Updated content"}}
        cache.set("123", updated)
        got = cache.get("123")
        assert got["sections"]["job_posting"] == "Updated content"

    def test_ttl_expiry(self, cache):
        cache.set("123", SAMPLE_RESULT, ttl_days=0)
        got = cache.get("123")
        assert got is None

    def test_ttl_zero_days_immediate_expiry(self, cache):
        """A 0-day TTL expires immediately."""
        cache.set("123", SAMPLE_RESULT, ttl_days=0)
        assert cache.get("123") is None

    def test_ttl_one_day(self, cache):
        """1-day TTL should still be valid (not expired)."""
        cache.set("123", SAMPLE_RESULT, ttl_days=1)
        got = cache.get("123")
        assert got is not None
        assert got["job_id"] == "123"

    def test_default_ttl(self, cache):
        cache.set("123", SAMPLE_RESULT)
        got = cache.get("123")
        assert got is not None
        assert got["job_id"] == "123"

    def test_invalidate_removes_entry(self, cache):
        cache.set("123", SAMPLE_RESULT)
        cache.invalidate("123")
        assert cache.get("123") is None

    def test_clear_expired(self, cache):
        cache.set("expired", SAMPLE_RESULT, ttl_days=0)
        cache.set("valid", SAMPLE_RESULT, ttl_days=1)
        cache.clear_expired()
        assert cache.get("expired") is None
        assert cache.get("valid") is not None

    def test_clear_all(self, cache):
        cache.set("123", SAMPLE_RESULT)
        cache.set("456", SAMPLE_RESULT)
        cache.clear_all()
        assert cache.get("123") is None
        assert cache.get("456") is None

    def test_get_many_all_cached(self, cache):
        cache.set("123", SAMPLE_RESULT)
        cache.set("456", SAMPLE_RESULT)
        result = cache.get_many(["123", "456"])
        assert len(result) == 2
        assert "123" in result
        assert "456" in result

    def test_get_many_some_missing(self, cache):
        cache.set("123", SAMPLE_RESULT)
        result = cache.get_many(["123", "456"])
        assert len(result) == 1
        assert "123" in result
        assert "456" not in result

    def test_get_many_all_missing(self, cache):
        result = cache.get_many(["999", "888"])
        assert result == {}

    def test_get_many_empty_list(self, cache):
        assert cache.get_many([]) == {}

    def test_get_many_with_expired(self, cache):
        cache.set("good", SAMPLE_RESULT, ttl_days=1)
        cache.set("stale", SAMPLE_RESULT, ttl_days=0)
        result = cache.get_many(["good", "stale"])
        assert "good" in result
        assert "stale" not in result
        # Stale is removed from DB
        assert cache.get("stale") is None

    def test_stores_arbitrary_dict(self, cache):
        complex_result = {
            "url": "https://example.com",
            "sections": {
                "job_posting": "Some text\nwith multiple\nlines",
                "extra_section": "more data",
            },
            "section_errors": {},
            "job_id": "789",
        }
        cache.set("789", complex_result)
        got = cache.get("789")
        assert got["sections"]["job_posting"] == "Some text\nwith multiple\nlines"
        assert got["sections"]["extra_section"] == "more data"

    def test_persistence_across_instances(self, tmp_path):
        db_path = tmp_path / "job-cache.db"
        result = {**SAMPLE_RESULT, "job_id": "persist"}
        c1 = JobCache(db_path)
        c1.set("persist", result)

        c2 = JobCache(db_path)
        got = c2.get("persist")
        assert got is not None
        assert got["job_id"] == "persist"

    def test_get_returns_copy_not_reference(self, cache):
        cache.set("123", SAMPLE_RESULT)
        got = cache.get("123")
        got["sections"]["job_posting"] = "Modified"
        # Should not affect cache
        got2 = cache.get("123")
        assert (
            got2["sections"]["job_posting"]
            == "Senior Engineer at Google\nSan Francisco"
        )
