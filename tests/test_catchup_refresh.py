"""Recovery is one source probe per trigger, without a self-dispatch chain."""
import copy
import json
import time
import urllib.request
from pathlib import Path

import pytest

import catchup_refresh as catchup
import sync_source


def dataset(*, price="stale", book="ok", strategy="ok"):
    return {"meta": {"source_blobs": {"live_track.json": "old"}}, "health": {"feeds": [
        {"feed": "Price / NAV (live_track)", "level": price},
        {"feed": "Executed portfolio (engine anchor)", "level": book},
        {"feed": "Strategy equity (multi_strategy)", "level": strategy},
    ]}}


@pytest.mark.parametrize("price,book,expected", [("ok", "ok", False), ("stale", "ok", True),
                                                ("ok", "stale", True)])
def test_only_daily_or_core_book_coverage_needs_recovery(price, book, expected):
    assert catchup.needs_catchup(dataset(price=price, book=book)) is expected


def test_other_stale_feeds_are_not_recoverable_by_a_daily_refresh():
    assert not catchup.needs_catchup(dataset(price="ok", strategy="stale"))


def test_absent_health_is_not_reported_as_current(monkeypatch, capsys):
    monkeypatch.setattr(catchup, "load_dataset", lambda pid: {})
    monkeypatch.setattr("sys.argv", ["catchup_refresh.py", "schedule"])
    assert catchup.main() == 0
    report = capsys.readouterr().out
    assert "no stale price/portfolio feed reported" in report
    assert "current" not in report


@pytest.mark.parametrize("mode", ["wait", "schedule"])
def test_repeated_triggers_and_exhausted_legacy_chains_never_wait_or_dispatch(monkeypatch, mode):
    blob = dataset()
    before = copy.deepcopy(blob)
    monkeypatch.setattr(catchup, "load_dataset", lambda pid: blob)
    monkeypatch.setattr(time, "sleep", lambda *a: pytest.fail("Sleeping runner"))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: pytest.fail("Network dispatch"))
    for attempt in [*range(9), 0, 0, 8, 0, 0]:
        monkeypatch.setattr("sys.argv", ["catchup_refresh.py", mode, "--attempt", str(attempt)])
        assert catchup.main() == 0
    assert blob == before, "Stale health must not be cleared by a recovery trigger"


@pytest.mark.parametrize("attempt", [-1, catchup.MAX_ATTEMPTS + 1])
def test_invalid_legacy_attempt_is_rejected(monkeypatch, attempt):
    monkeypatch.setattr("sys.argv", ["catchup_refresh.py", "schedule", "--attempt", str(attempt)])
    with pytest.raises(ValueError, match="Invalid"):
        catchup.main()


def test_later_publication_is_detected_after_any_number_of_unchanged_triggers(monkeypatch, tmp_path):
    path = tmp_path / "dataset.json"
    blob = dataset()
    path.write_text(json.dumps(blob))
    output = tmp_path / "outputs"
    snapshot = {"commit": "unrelated-head", "files": {"live_track.json": "old"}}
    monkeypatch.setattr(sync_source, "ACTIVE_PORTFOLIO_IDS", ["paper"])
    monkeypatch.setattr(sync_source, "load_registry", lambda pid: {"source": {}})
    monkeypatch.setattr(sync_source, "dataset_path", lambda pid: path)
    monkeypatch.setattr(sync_source, "resolve_snapshot", lambda src: snapshot)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr("sys.argv", ["sync_source.py", "--only-if-changed"])
    for _ in range(12):
        assert sync_source.main() == 0
        assert output.read_text().splitlines()[-1] == "rebuild=false"
    snapshot["files"]["live_track.json"] = "recovered"
    assert sync_source.main() == 0
    assert output.read_text().splitlines()[-1] == "rebuild=true"
    assert json.loads(path.read_text()) == blob  # probe cannot assert freshness
    # Simulate successful validated consumption of the new bytes.
    blob["meta"]["source_blobs"]["live_track.json"] = "recovered"
    path.write_text(json.dumps(blob))
    assert sync_source.main() == 0
    assert output.read_text().splitlines()[-1] == "rebuild=false"


def test_probe_api_failure_is_not_treated_as_unchanged(monkeypatch):
    def fail(src):
        raise OSError("API unavailable")
    monkeypatch.setattr(sync_source, "resolve_snapshot", fail)
    monkeypatch.setattr("sys.argv", ["sync_source.py", "--only-if-changed"])
    with pytest.raises(OSError, match="API unavailable"):
        sync_source.main()


def test_workflow_retains_probe_and_publication_guards_without_a_dispatch_loop():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/daily_monitor.yml").read_text()
    assert "cron: '17 * * * *'" in workflow
    assert "python scripts/sync_source.py --only-if-changed" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "ref: main" in workflow
    for command in ["pipeline.py", "pytest tests/ -q", "check_capture_integrity.py"]:
        assert command in workflow
    assert "actions: write" not in workflow
    assert "catchup_refresh.py wait" not in workflow
    assert "gh workflow run" not in workflow
