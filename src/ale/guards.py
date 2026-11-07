"""Bounded iteration: an iteration cap plus a wall-clock budget (RD 0.4 section 3).

Every loop whose termination is not obvious must run under :func:`bounded` or
:func:`bounded_range`. When the budget is exhausted the loop either raises a diagnosable
:class:`ConvergenceError` (default) or stops cleanly (``on_exhaust="stop"``).

The guard is purely cooperative: one ``clock()`` call per :meth:`Budget.tick`, no threads
and no signals, so it behaves identically on Windows, macOS and Linux.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Literal, get_args

__all__ = [
    "SNAPSHOT_REPR_MAX",
    "Budget",
    "ConvergenceError",
    "ExhaustReason",
    "OnExhaust",
    "bounded",
    "bounded_range",
]

log = logging.getLogger(__name__)

ExhaustReason = Literal["max_iter", "time_budget"]
OnExhaust = Literal["raise", "stop"]
Clock = Callable[[], float]

#: Maximum length of ``repr(state_snapshot)`` in :meth:`ConvergenceError.to_report`.
SNAPSHOT_REPR_MAX = 2000
_TRUNCATED = "…[truncated]"
_ON_EXHAUST_VALUES: tuple[str, ...] = get_args(OnExhaust)


class ConvergenceError(RuntimeError):
    """A bounded loop exhausted its iteration cap or its time budget."""

    label: str
    reason: ExhaustReason
    iterations: int
    elapsed_s: float
    state_snapshot: object | None
    snapshot_error: str | None

    def __init__(
        self,
        label: str,
        reason: ExhaustReason,
        iterations: int,
        elapsed_s: float,
        state_snapshot: object | None = None,
        snapshot_error: str | None = None,
    ) -> None:
        super().__init__(
            f"{label}: budget exhausted ({reason}) after {iterations} iterations "
            f"in {elapsed_s:.3f} s"
        )
        self.label = label
        self.reason = reason
        self.iterations = iterations
        self.elapsed_s = elapsed_s
        self.state_snapshot = state_snapshot
        self.snapshot_error = snapshot_error

    def __reduce__(self) -> tuple[type[ConvergenceError], tuple[object, ...]]:
        return (
            type(self),
            (
                self.label,
                self.reason,
                self.iterations,
                self.elapsed_s,
                self.state_snapshot,
                self.snapshot_error,
            ),
        )

    def to_report(self) -> dict[str, object]:
        """JSON-serialisable summary; the snapshot is ``repr``-ed and truncated."""
        try:
            snapshot = repr(self.state_snapshot)
        except Exception as exc:  # a broken __repr__ must not hide the diagnosis
            snapshot = f"<unrepresentable snapshot: {exc!r}>"
        if len(snapshot) > SNAPSHOT_REPR_MAX:
            snapshot = snapshot[:SNAPSHOT_REPR_MAX] + _TRUNCATED
        return {
            "label": self.label,
            "reason": self.reason,
            "iterations": self.iterations,
            "elapsed_s": round(self.elapsed_s, 3),
            "snapshot": snapshot,
            "snapshot_error": self.snapshot_error,
        }


def _check_max_iter(max_iter: object) -> int:
    if isinstance(max_iter, bool) or not isinstance(max_iter, int):
        raise TypeError(f"max_iter must be an int, got {type(max_iter).__name__}")
    if max_iter < 1:
        raise ValueError(f"max_iter must be >= 1, got {max_iter}")
    return max_iter


def _check_time_budget(time_budget_s: object) -> float:
    if isinstance(time_budget_s, bool) or not isinstance(time_budget_s, int | float):
        raise TypeError(f"time_budget_s must be a number, got {type(time_budget_s).__name__}")
    value = float(time_budget_s)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"time_budget_s must be a finite number > 0, got {time_budget_s}")
    return value


def _check_label(label: object) -> str:
    if not isinstance(label, str):
        raise TypeError(f"label must be a str, got {type(label).__name__}")
    if not label:
        raise ValueError("label must not be empty")
    return label


class Budget:
    """Iteration and time budget of one bounded loop; call :meth:`tick` once per iteration."""

    __slots__ = (
        "_calls",
        "_clock",
        "_on_exhaust",
        "_snapshot",
        "_start",
        "exhausted_reason",
        "iterations",
        "label",
        "max_iter",
        "time_budget_s",
    )

    def __init__(
        self,
        max_iter: int,
        time_budget_s: float,
        *,
        label: str,
        snapshot: Callable[[], object] | None = None,
        on_exhaust: OnExhaust = "raise",
        clock: Clock = time.monotonic,
    ) -> None:
        self.max_iter: int = _check_max_iter(max_iter)
        self.time_budget_s: float = _check_time_budget(time_budget_s)
        self.label: str = _check_label(label)
        if snapshot is not None and not callable(snapshot):
            raise TypeError("snapshot must be callable or None")
        if on_exhaust not in _ON_EXHAUST_VALUES:
            raise ValueError(f"on_exhaust must be one of {_ON_EXHAUST_VALUES}, got {on_exhaust!r}")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._snapshot = snapshot
        self._on_exhaust: OnExhaust = on_exhaust
        self._clock = clock
        self._start: float | None = None
        self._calls = 0
        self.iterations: int = 0
        self.exhausted_reason: ExhaustReason | None = None

    def start(self) -> None:
        """Read the start time (done on entering :func:`bounded`); later calls are no-ops."""
        if self._start is None:
            self._start = self._clock()

    def tick(self) -> bool:
        """Account for one iteration; ``True`` if it may run.

        On exhaustion: raises :class:`ConvergenceError` (``on_exhaust="raise"``) or
        returns ``False`` (``on_exhaust="stop"``, also on every later call).
        """
        if self.exhausted_reason is not None:
            return False
        start = self._start
        if start is None:  # used without bounded(): start on the first tick
            start = self._start = self._clock()
        k = self._calls + 1
        self._calls = k
        if k > self.max_iter:
            return self._exhaust("max_iter", self._clock() - start)
        elapsed = self._clock() - start
        if elapsed > self.time_budget_s:
            return self._exhaust("time_budget", elapsed)
        self.iterations = k
        return True

    def elapsed_s(self) -> float:
        """Seconds since the start (0.0 before the start)."""
        if self._start is None:
            return 0.0
        return self._clock() - self._start

    def remaining_s(self) -> float:
        """Seconds left in the time budget, never negative."""
        return max(0.0, self.time_budget_s - self.elapsed_s())

    def _exhaust(self, reason: ExhaustReason, elapsed: float) -> bool:
        self.exhausted_reason = reason
        log.warning(
            "budget exhausted: label=%s reason=%s iterations=%d elapsed_s=%.3f",
            self.label,
            reason,
            self.iterations,
            elapsed,
            extra={
                "event": "guards.exhausted",
                "label": self.label,
                "reason": reason,
                "iterations": self.iterations,
                "elapsed_s": round(elapsed, 3),
            },
        )
        if self._on_exhaust == "stop":
            return False
        state: object | None = None
        snapshot_error: str | None = None
        if self._snapshot is not None:
            try:
                state = self._snapshot()
            except Exception as exc:
                snapshot_error = repr(exc)
        raise ConvergenceError(self.label, reason, self.iterations, elapsed, state, snapshot_error)


@contextmanager
def _started(budget: Budget) -> Iterator[Budget]:
    budget.start()
    yield budget


def bounded(
    max_iter: int,
    time_budget_s: float,
    *,
    label: str,
    snapshot: Callable[[], object] | None = None,
    on_exhaust: OnExhaust = "raise",
    clock: Clock = time.monotonic,
) -> AbstractContextManager[Budget]:
    """Context manager yielding a started :class:`Budget`.

    Arguments are validated immediately (``ValueError`` / ``TypeError``); the start time
    is read on entering the ``with`` block.
    """
    budget = Budget(
        max_iter,
        time_budget_s,
        label=label,
        snapshot=snapshot,
        on_exhaust=on_exhaust,
        clock=clock,
    )
    return _started(budget)


def _range(budget: Budget) -> Iterator[int]:
    budget.start()
    i = 0
    while budget.tick():
        yield i
        i += 1


def bounded_range(
    max_iter: int,
    time_budget_s: float,
    *,
    label: str,
    snapshot: Callable[[], object] | None = None,
    on_exhaust: OnExhaust = "raise",
    clock: Clock = time.monotonic,
) -> Iterator[int]:
    """Yield 0, 1, 2, ... with one :meth:`Budget.tick` per item.

    Arguments are validated immediately; the start time is read on the first ``next()``.
    """
    budget = Budget(
        max_iter,
        time_budget_s,
        label=label,
        snapshot=snapshot,
        on_exhaust=on_exhaust,
        clock=clock,
    )
    return _range(budget)
