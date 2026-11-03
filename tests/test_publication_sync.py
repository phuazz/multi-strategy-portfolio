"""Publication races and source identity; no network or real-clock dependency.

Python datetime months are 1-indexed.
"""
import hashlib
import json
from datetime import datetime, timezone

import pytest

import source_revision as revision
import sources
import sync_source
import sentinel_check
from config import load_registry
from portfolio_freshness import evaluate_book, expected_book_session


REG = load_registry("multi-strategy-portfolio")


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.mark.parametrize("clock,expected", [
    ("2026-11-02T20:59:00Z", "2026-10-26"),  # before the core market closes
    ("2026-11-02T21:00:00Z", "2026-11-02"),  # month boundary, standard time
    ("2027-01-01T23:00:00Z", "2026-12-28"),  # year boundary, market holiday
    ("2027-01-04T21:00:00Z", "2027-01-04"),
    ("2026-09-07T22:00:00Z", "2026-08-31"),  # holiday Monday, no invented fill
    ("2026-09-08T19:59:00Z", "2026-08-31"),
    ("2026-09-08T20:00:00Z", "2026-09-08"),  # rolls forward, daylight time
])
def test_book_expectation_follows_completed_exchange_closes(clock, expected):
    assert expected_book_session(instant(clock)).isoformat() == expected


def test_naive_book_clock_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        expected_book_session(datetime(2026, 11, 3))


@pytest.mark.parametrize("anchor,end,level", [
    ("2026-10-30", "2026-10-30", "stale"),
    ("2026-11-02", "2026-10-30", "stale"),
    ("2026-10-30", "2026-11-02", "stale"),
    ("2026-11-02", "2026-11-02", "ok"),
    (None, "2026-11-02", "stale"),
])
def test_prices_do_not_substitute_for_book_coverage(anchor, end, level):
    assert evaluate_book(anchor, end, instant("2026-11-03T04:00:00Z"))["level"] == level


def test_green_daily_prices_do_not_mask_missing_weekly_fill():
    import validate
    # Reproduce the incident: all existing feed budgets pass.
    bundle = {
        "live_track.json": {"live_dates": ["2026-11-02"], "anchor_date": "2026-10-30"},
        "multi_strategy.json": {"common_end": "2026-10-30"},
        "risk_overlay.json": {"panel_end_date": "2026-10-30"},
    }
    now = instant("2026-11-03T04:00:00Z")
    health = validate.run(bundle, REG, now.date(), {}, True, "ok", now_utc=now)
    assert health["level"] == "stale"
    book = next(f for f in health["feeds"] if f["feed"].startswith("Executed portfolio"))
    assert book["expected"] == "2026-11-02"
    assert all(f["level"] == "ok" for f in health["feeds"] if f is not book)
    assert any("Current prices" in m for m in health["messages"])


def git_hash(content):
    return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()


def source_fixture(monkeypatch):
    src = {"repo": "owner/engine", "api_base": "https://api.github.com/repos/owner/engine",
           "ref": "main", "files": ["live_track.json"], "history_files": ["history.json"]}
    content = b'{"anchor_date":"2026-11-02"}'
    snapshot = {"commit": "a" * 40,
                "files": {"live_track.json": git_hash(content), "history.json": None}}
    monkeypatch.setattr(sources, "resolve_snapshot", lambda s: snapshot)
    return src, content, snapshot


def test_bundle_is_pinned_and_hash_verified(monkeypatch):
    src, content, snapshot = source_fixture(monkeypatch)
    requested = []

    def fetch(url):
        requested.append(url)
        assert f"/{snapshot['commit']}/data/" in url
        assert "/main/" not in url
        return content

    monkeypatch.setattr(sources, "_fetch_url", fetch)
    bundle = sources.load_sources({"source": src})
    assert bundle["source_commit"] == snapshot["commit"]
    assert bundle["source_blobs"] == snapshot["files"]
    assert len(requested) == 1


def test_wrong_blob_cannot_be_published(monkeypatch):
    src, _, _ = source_fixture(monkeypatch)
    monkeypatch.setattr(sources, "_fetch_url", lambda url: b'{}')
    with pytest.raises(RuntimeError, match="blob verification"):
        sources.load_sources({"source": src})


def test_published_history_download_failure_cannot_silently_fall_back(monkeypatch):
    src, content, snapshot = source_fixture(monkeypatch)
    snapshot["files"]["history.json"] = git_hash(b'{}')

    def fetch(url):
        if url.endswith("history.json"):
            raise OSError("connection interrupted")
        return content

    monkeypatch.setattr(sources, "_fetch_url", fetch)
    with pytest.raises(OSError, match="interrupted"):
        sources.load_sources({"source": src})


def test_resolver_uses_immutable_trees_and_checks_required_files(monkeypatch):
    src = REG["source"]
    responses = [
        {"sha": "a" * 40},
        {"tree": [{"path": "data", "type": "tree", "sha": "b" * 40}]},
        {"tree": [{"path": fn, "type": "blob", "sha": "c" * 40} for fn in src["files"]]},
    ]
    urls = []

    def api(url):
        urls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(revision, "api_json", api)
    snapshot = revision.resolve_snapshot(src)
    assert urls[1].endswith("/git/trees/" + "a" * 40)
    assert snapshot["files"][src["history_files"][0]] is None


def test_unrelated_engine_commit_is_a_noop():
    meta = {"source_commit": "old", "source_blobs": {"live_track.json": "same"}}
    assert revision.changed_files(meta, {"commit": "new", "files": meta["source_blobs"]}, {}) == []


def test_legacy_bootstrap_reads_recorded_commit(monkeypatch):
    refs = []
    monkeypatch.setattr(revision, "resolve_snapshot",
                        lambda src, ref: refs.append(ref) or {"files": {"live_track.json": "old"}})
    assert revision.changed_files({"source_commit": "recorded"},
                                  {"files": {"live_track.json": "new"}}, {}) == ["live_track.json"]
    assert refs == ["recorded"]


@pytest.mark.parametrize("published,now,overdue", [
    ("2026-10-31T23:30:00Z", "2026-11-01T01:31:00Z", True),  # month boundary
    ("2026-12-31T23:30:00Z", "2027-01-01T01:29:00Z", False),  # year boundary
    ("2026-12-31T23:30:00Z", "2027-01-01T01:30:00Z", False),  # exact budget
    ("2026-12-31T23:30:00Z", "2027-01-01T01:31:00Z", True),
])
def test_sync_budget_uses_changed_file_time_not_unrelated_head(monkeypatch, published, now, overdue):
    urls = []

    def api(url):
        urls.append(url)
        return [{"commit": {"committer": {"date": published}}}]

    monkeypatch.setattr(revision, "api_json", api)
    result = revision.overdue_source_files(
        {"source_blobs": {"live_track.json": "old"}},
        {"commit": "pinned", "files": {"live_track.json": "new"}},
        {"api_base": "https://api.github.com/repos/owner/engine"}, instant(now))
    assert bool(result) == overdue
    assert "path=data/live_track.json&sha=pinned" in urls[0]


@pytest.mark.parametrize("changed,only_if_changed,rebuild", [
    ([], True, False), (["history.json"], True, True), ([], False, True),
])
def test_probe_skips_only_unchanged_hourly_runs(monkeypatch, tmp_path, changed, only_if_changed, rebuild):
    dataset = tmp_path / "portfolio.json"
    dataset.write_text(json.dumps({"meta": {"source_commit": "old", "source_blobs": {"live_track.json": "same"}}}))
    output = tmp_path / "output.txt"
    monkeypatch.setattr(sync_source, "dataset_path", lambda pid: dataset)
    monkeypatch.setattr(sync_source, "resolve_snapshot", lambda src: {"commit": "new", "files": {}})
    monkeypatch.setattr(sync_source, "changed_files", lambda *args: changed)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr("sys.argv", ["sync_source.py"] + (["--only-if-changed"] if only_if_changed else []))
    assert sync_source.main() == 0
    assert output.read_text().strip() == f"rebuild={str(rebuild).lower()}"


def test_probe_bootstraps_unverified_legacy_provenance(monkeypatch, tmp_path):
    dataset = tmp_path / "portfolio.json"
    dataset.write_text(json.dumps({"meta": {"source_commit": "already-current"}}))
    output = tmp_path / "output.txt"
    monkeypatch.setattr(sync_source, "dataset_path", lambda pid: dataset)
    monkeypatch.setattr(sync_source, "resolve_snapshot", lambda src: {
        "commit": "already-current", "files": {"live_track.json": "same"}})
    monkeypatch.setattr(sync_source, "changed_files", lambda *args: pytest.fail("Legacy provenance must force a build"))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr("sys.argv", ["sync_source.py", "--only-if-changed"])
    assert sync_source.main() == 0
    assert output.read_text().strip() == "rebuild=true"


@pytest.mark.parametrize("overdue,error,expected", [([], False, 0), (["history.json"], False, 1), ([], True, 1)])
def test_deployed_sentinel_independently_checks_source_publication(monkeypatch, overdue, error, expected):
    now = instant("2026-11-03T08:00:00Z")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    blob = {"meta": {"live_asOf": "2026-11-02", "portfolio_anchor": "2026-11-02",
                     "strategy_asOf": "2026-11-02"}, "health": {"level": "ok"}}
    monkeypatch.setattr(sentinel_check, "datetime", Clock)
    monkeypatch.setattr(sentinel_check, "fetch_deployed_dataset", lambda pid: blob)

    def snapshot(src):
        if error:
            raise OSError("API unavailable")
        return {}

    monkeypatch.setattr(sentinel_check, "resolve_snapshot", snapshot)
    monkeypatch.setattr(sentinel_check, "overdue_source_files", lambda *args: overdue)
    assert sentinel_check.main() == expected
