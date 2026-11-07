"""Ticket 0.4 eval section 1: ``ale.guards`` (G01-G09) plus edge cases."""

from __future__ import annotations

import json
import logging
import math
import pickle
import sys
import time
from typing import Any

import pytest
from fixtures import FakeClock

from ale.guards import (
    SNAPSHOT_REPR_MAX,
    Budget,
    ConvergenceError,
    bounded,
    bounded_range,
)


def test_G01_max_iter() -> None:
    with bounded(100, 60, label="t") as budget:
        for _ in range(100):
            assert budget.tick() is True
        assert budget.iterations == 100
        with pytest.raises(ConvergenceError) as info:
            budget.tick()
    err = info.value
    assert err.reason == "max_iter"
    assert err.iterations == 100
    assert err.label == "t"
    assert budget.exhausted_reason == "max_iter"


def test_G02_time_budget(fake_clock: FakeClock) -> None:
    allowed = 0
    with (
        pytest.raises(ConvergenceError) as info,
        bounded(10**6, 5.0, label="t", clock=fake_clock) as budget,
    ):
        while True:
            fake_clock.advance(1.0)
            budget.tick()
            allowed += 1
    err = info.value
    assert allowed == 5  # tick 5 allowed: elapsed 5.0 is not > 5.0
    assert err.reason == "time_budget"
    assert err.iterations == 5
    assert err.elapsed_s == 6.0


def test_G03_snapshot_called_once_on_exhaustion() -> None:
    calls: list[int] = []
    state = {"best": 1.5}

    def snapshot() -> object:
        calls.append(1)
        return state

    with (
        pytest.raises(ConvergenceError) as info,
        bounded(3, 60, label="snap", snapshot=snapshot) as b,
    ):
        for _ in range(3):
            b.tick()
            assert calls == []
        b.tick()
    assert calls == [1]
    assert info.value.state_snapshot is state
    assert info.value.snapshot_error is None


def test_G03_snapshot_not_called_without_exhaustion() -> None:
    calls: list[int] = []
    with bounded(5, 60, label="ok", snapshot=lambda: calls.append(1)) as budget:
        for _ in range(5):
            assert budget.tick()
    assert calls == []
    seen = []
    for i in bounded_range(4, 60, label="ok", snapshot=lambda: calls.append(1)):
        seen.append(i)
        if i == 3:  # the caller converged: leaving early never exhausts the budget
            break
    assert seen == [0, 1, 2, 3]
    assert calls == []


def test_G03_snapshot_raising_keyerror() -> None:
    def snapshot() -> object:
        raise KeyError("missing")

    with pytest.raises(ConvergenceError) as info:
        for _ in bounded_range(2, 60, label="bad-snap", snapshot=snapshot):
            pass
    err = info.value
    assert err.reason == "max_iter"
    assert err.state_snapshot is None
    assert err.snapshot_error is not None
    assert "KeyError" in err.snapshot_error


def test_G04_stop_mode() -> None:
    assert list(bounded_range(7, 60, label="t", on_exhaust="stop")) == list(range(7))

    calls: list[int] = []
    with bounded(7, 60, label="t", on_exhaust="stop", snapshot=lambda: calls.append(1)) as b:
        results = [b.tick() for _ in range(8)]
    assert results == [True] * 7 + [False]
    assert b.exhausted_reason == "max_iter"
    assert b.iterations == 7
    assert calls == []
    assert b.tick() is False  # stays exhausted


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"max_iter": 0}, id="max_iter=0"),
        pytest.param({"max_iter": -1}, id="max_iter=-1"),
        pytest.param({"max_iter": True}, id="max_iter=True"),
        pytest.param({"max_iter": 1.5}, id="max_iter=1.5"),
        pytest.param({"time_budget_s": 0}, id="time_budget_s=0"),
        pytest.param({"time_budget_s": -1}, id="time_budget_s=-1"),
        pytest.param({"time_budget_s": math.inf}, id="time_budget_s=inf"),
        pytest.param({"time_budget_s": math.nan}, id="time_budget_s=nan"),
        pytest.param({"label": ""}, id="label=empty"),
    ],
)
def test_G05_arg_validation(kwargs: dict[str, Any]) -> None:
    args: dict[str, Any] = {"max_iter": 10, "time_budget_s": 1.0, "label": "t", **kwargs}
    with pytest.raises((ValueError, TypeError)):
        bounded(args["max_iter"], args["time_budget_s"], label=args["label"])
    with pytest.raises((ValueError, TypeError)):
        bounded_range(args["max_iter"], args["time_budget_s"], label=args["label"])


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"time_budget_s": "1"}, id="time_budget_s=str"),
        pytest.param({"time_budget_s": True}, id="time_budget_s=True"),
        pytest.param({"label": 3}, id="label=int"),
        pytest.param({"on_exhaust": "ignore"}, id="on_exhaust=bad"),
        pytest.param({"snapshot": 3}, id="snapshot=not-callable"),
        pytest.param({"clock": 3}, id="clock=not-callable"),
    ],
)
def test_G05_arg_validation_other(kwargs: dict[str, Any]) -> None:
    args: dict[str, Any] = {"max_iter": 10, "time_budget_s": 1.0, "label": "t", **kwargs}
    with pytest.raises((ValueError, TypeError)):
        Budget(**args)


def test_G06_real_infinite_loop() -> None:
    t0 = time.monotonic()
    with pytest.raises(ConvergenceError) as info, bounded(10**12, 0.2, label="inf") as budget:
        while True:
            budget.tick()
    wall = time.monotonic() - t0
    assert info.value.reason == "time_budget"
    assert wall < 0.6, f"guard tripped after {wall:.3f} s"
    assert info.value.elapsed_s > 0.2


def _traced() -> bool:
    """True under a tracer/profiler (e.g. coverage), where timings are not meaningful."""
    if sys.gettrace() is not None or sys.getprofile() is not None:
        return True
    monitoring = getattr(sys, "monitoring", None)
    return monitoring is not None and any(monitoring.get_tool(i) is not None for i in range(6))


def test_G07_overhead() -> None:
    n = 10**6
    with bounded(n, 3600.0, label="overhead") as budget:
        t0 = time.perf_counter()
        for _ in range(n):
            budget.tick()
        dt = time.perf_counter() - t0
    assert budget.iterations == n
    print(f"G07: {n} ticks in {dt:.3f} s")
    if sys.platform.startswith("linux") and not _traced():
        assert dt < 1.5, f"{n} ticks took {dt:.3f} s"


def test_G08_report() -> None:
    class Big:
        def __repr__(self) -> str:
            return "x" * 10_000

    with pytest.raises(ConvergenceError) as info:
        for _ in bounded_range(1, 60, label="rep", snapshot=Big):
            pass
    report = info.value.to_report()
    json.dumps(report)
    assert set(report) == {
        "label",
        "reason",
        "iterations",
        "elapsed_s",
        "snapshot",
        "snapshot_error",
    }
    assert report["label"] == "rep"
    assert report["reason"] == "max_iter"
    assert report["iterations"] == 1
    assert report["snapshot"] == "x" * SNAPSHOT_REPR_MAX + "…[truncated]"
    assert SNAPSHOT_REPR_MAX == 2000
    assert report["snapshot_error"] is None


def test_G08_report_rounding_and_short_snapshot() -> None:
    err = ConvergenceError("lbl", "time_budget", 7, 1.23456789, {"k": [1, 2]}, None)
    report = err.to_report()
    assert report["elapsed_s"] == 1.235
    assert report["snapshot"] == "{'k': [1, 2]}"
    json.dumps(report)


def test_G08_report_unrepresentable_snapshot() -> None:
    class Broken:
        def __repr__(self) -> str:
            raise RuntimeError("no repr")

    report = ConvergenceError("lbl", "max_iter", 1, 0.0, Broken()).to_report()
    assert isinstance(report["snapshot"], str)
    assert "no repr" in report["snapshot"]
    json.dumps(report)


def test_G08_pickle_round_trip() -> None:
    err = ConvergenceError("pk", "time_budget", 12, 3.5, {"x": [1, 2]}, "KeyError('a')")
    back = pickle.loads(pickle.dumps(err))
    assert isinstance(back, ConvergenceError)
    assert isinstance(back, RuntimeError)
    assert (back.label, back.reason, back.iterations, back.elapsed_s) == (
        "pk",
        "time_budget",
        12,
        3.5,
    )
    assert back.state_snapshot == {"x": [1, 2]}
    assert back.snapshot_error == "KeyError('a')"
    assert str(back) == str(err)
    assert back.to_report() == err.to_report()


@pytest.fixture
def guards_caplog(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> Any:
    # The CLI's configure_logging() may have set propagate=False on the `ale` logger.
    monkeypatch.setattr(logging.getLogger("ale"), "propagate", True)
    caplog.set_level(logging.DEBUG, logger="ale.guards")
    return caplog


def test_G09_logging(guards_caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(ConvergenceError), bounded(3, 60, label="my-loop") as budget:
        while True:
            budget.tick()
    records = [r for r in guards_caplog.records if r.name == "ale.guards"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.WARNING
    assert "my-loop" in record.getMessage()
    assert "max_iter" in record.getMessage()


def test_G09_logging_stop_mode_once(
    guards_caplog: pytest.LogCaptureFixture, fake_clock: FakeClock
) -> None:
    with bounded(100, 1.0, label="stopper", on_exhaust="stop", clock=fake_clock) as budget:
        assert budget.tick()
        fake_clock.advance(2.0)
        assert budget.tick() is False
        assert budget.tick() is False
    assert budget.exhausted_reason == "time_budget"
    warnings = [r for r in guards_caplog.records if r.name == "ale.guards"]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    assert "stopper" in warnings[0].getMessage()
    assert "time_budget" in warnings[0].getMessage()


def test_budget_elapsed_and_remaining(fake_clock: FakeClock) -> None:
    budget = Budget(10, 5.0, label="b", clock=fake_clock)
    assert budget.elapsed_s() == 0.0  # not started yet
    assert budget.remaining_s() == 5.0
    with bounded(10, 5.0, label="b", clock=fake_clock) as b:
        fake_clock.advance(2.0)
        assert b.elapsed_s() == 2.0
        assert b.remaining_s() == 3.0
        fake_clock.advance(10.0)
        assert b.remaining_s() == 0.0
    assert (b.label, b.max_iter, b.time_budget_s) == ("b", 10, 5.0)


def test_budget_start_read_on_enter(fake_clock: FakeClock) -> None:
    cm = bounded(10, 5.0, label="enter", clock=fake_clock)
    fake_clock.advance(100.0)  # time before entering does not count
    with cm as budget:
        assert budget.tick()
        assert budget.elapsed_s() == 0.0


def test_bounded_range_start_on_first_next(fake_clock: FakeClock) -> None:
    it = bounded_range(3, 5.0, label="lazy", clock=fake_clock)
    fake_clock.advance(100.0)  # time before the first next() does not count
    assert next(it) == 0
    assert next(it) == 1
    assert next(it) == 2
    with pytest.raises(ConvergenceError) as info:  # raise mode: the 4th tick exhausts
        next(it)
    assert info.value.reason == "max_iter"
    assert info.value.elapsed_s == 0.0


def test_bounded_range_time_budget_stop(fake_clock: FakeClock) -> None:
    seen = []
    for i in bounded_range(10**6, 3.0, label="r", on_exhaust="stop", clock=fake_clock):
        seen.append(i)
        fake_clock.advance(1.0)
    assert seen == [0, 1, 2, 3]  # elapsed 0, 1, 2, 3 allowed; 4 > 3 stops


def test_budget_without_context_starts_on_first_tick(fake_clock: FakeClock) -> None:
    budget = Budget(2, 5.0, label="bare", clock=fake_clock)
    fake_clock.advance(100.0)
    assert budget.tick()
    assert budget.tick()
    with pytest.raises(ConvergenceError) as info:
        budget.tick()
    assert info.value.iterations == 2
    assert info.value.elapsed_s == 0.0


def test_convergence_error_message() -> None:
    err = ConvergenceError("lbl", "max_iter", 4, 0.5)
    assert "lbl" in str(err)
    assert "max_iter" in str(err)
    assert err.state_snapshot is None
    assert err.snapshot_error is None


def test_budget_start_is_idempotent(fake_clock: FakeClock) -> None:
    budget = Budget(5, 5.0, label="twice", clock=fake_clock)
    budget.start()
    fake_clock.advance(3.0)
    budget.start()  # no-op: the first start time is kept
    assert budget.elapsed_s() == 3.0
