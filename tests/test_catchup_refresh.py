"""Recovery bounds and stop conditions, with no sleeps or GitHub writes."""
import json

import pytest

import catchup_refresh as catchup


def dataset(*, price="stale", book="ok", strategy="ok"):
    return {"meta": {"source_blobs": {"live_track.json": "old"}}, "health": {"feeds": [
        {"feed": "Price / NAV (live_track)", "level": price},
        {"feed": "Executed portfolio (engine anchor)", "level": book},
        {"feed": "Strategy equity (multi_strategy)", "level": strategy},
    ]}}


@pytest.mark.parametrize("price,book,expected", [("ok","ok",False), ("stale","ok",True),
                                                ("ok","stale",True)])
def test_only_missing_daily_or_core_book_coverage_starts_recovery(price, book, expected):
    assert catchup.needs_catchup(dataset(price=price, book=book)) is expected


def test_other_stale_feeds_do_not_create_an_unrelated_retry_loop():
    assert not catchup.needs_catchup(dataset(price="ok", strategy="stale"))


def test_recovery_is_bounded_and_last_fresh_run_stops_cleanly():
    for attempt in range(catchup.MAX_ATTEMPTS):
        assert catchup.next_attempt(dataset(), attempt) == attempt + 1
    with pytest.raises(RuntimeError, match="limit reached"):
        catchup.next_attempt(dataset(), catchup.MAX_ATTEMPTS)
    assert catchup.next_attempt(dataset(price="ok"), catchup.MAX_ATTEMPTS) is None


@pytest.mark.parametrize("attempt", [-1, catchup.MAX_ATTEMPTS + 1])
def test_invalid_attempt_cannot_start_a_new_chain(attempt):
    with pytest.raises(ValueError):
        catchup.next_attempt(dataset(), attempt)


def setup_wait(monkeypatch, blob=None):
    monkeypatch.setattr(catchup, "load_dataset", lambda pid: blob or dataset())
    monkeypatch.setattr(catchup, "load_registry", lambda pid: {"source": {}})


def test_fresh_source_does_not_sleep_or_call_the_api(monkeypatch):
    setup_wait(monkeypatch, dataset(price="ok"))
    monkeypatch.setattr(catchup, "resolve_snapshot", lambda *args: pytest.fail("Unnecessary source request"))
    assert catchup.wait_for_publication("test") == "already-fresh"


def test_late_source_is_seen_without_waiting_for_another_cron(monkeypatch):
    setup_wait(monkeypatch)
    clock = [0]
    calls = [0]

    def source(_):
        calls[0] += 1
        return {"files": {"live_track.json": "old" if calls[0] == 1 else "new"}}

    monkeypatch.setattr(catchup, "resolve_snapshot", source)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    assert catchup.wait_for_publication("test", 120, clock=lambda: clock[0], sleep=sleep) == "source-changed"
    assert sleeps == [60]


def test_unchanged_source_exhausts_only_its_bounded_wait_budget(monkeypatch):
    setup_wait(monkeypatch)
    monkeypatch.setattr(catchup, "resolve_snapshot", lambda src: {"files": {"live_track.json": "old"}})
    clock = [0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    assert catchup.wait_for_publication("test", 65, clock=lambda: clock[0], sleep=sleep) == "wait-budget-exhausted"
    assert sleeps == [60, 5] and clock[0] == 65


def test_source_check_failure_is_not_interpreted_as_no_change(monkeypatch):
    setup_wait(monkeypatch)

    def failed(src):
        raise OSError("API unavailable")

    monkeypatch.setattr(catchup, "resolve_snapshot", failed)
    with pytest.raises(OSError, match="unavailable"):
        catchup.wait_for_publication("test", timeout=0)


def test_dispatch_targets_only_the_existing_monitor_workflow(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/monitor")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-token")
    requests = []

    class Response:
        status = 204
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def open_request(request, timeout):
        requests.append(request)
        return Response()

    monkeypatch.setattr(catchup.urllib.request, "urlopen", open_request)
    catchup.dispatch(1)
    assert requests[0].full_url.endswith("/owner/monitor/actions/workflows/daily_monitor.yml/dispatches")
    assert json.loads(requests[0].data) == {"ref": "main", "inputs": {"catchup_attempt": "1"}}


@pytest.mark.parametrize("fresh,expected", [(False,[1]),(True,[])])
def test_schedule_dispatches_only_when_needed(monkeypatch, fresh, expected):
    monkeypatch.setattr(catchup, "load_dataset", lambda pid: dataset(price="ok" if fresh else "stale"))
    requested = []
    monkeypatch.setattr(catchup, "dispatch", requested.append)
    monkeypatch.setattr("sys.argv", ["catchup_refresh.py", "schedule", "--attempt", "0"])
    assert catchup.main() == 0
    assert requested == expected


def test_maximum_attempt_cannot_dispatch_a_ninth_followup(monkeypatch):
    monkeypatch.setattr(catchup, "load_dataset", lambda pid: dataset())
    monkeypatch.setattr(catchup, "dispatch", lambda *args: pytest.fail("Exceeded retry limit"))
    monkeypatch.setattr("sys.argv", ["catchup_refresh.py", "schedule", "--attempt", str(catchup.MAX_ATTEMPTS)])
    with pytest.raises(RuntimeError, match="operator action required"):
        catchup.main()
