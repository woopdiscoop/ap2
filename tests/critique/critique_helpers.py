"""Helpers of the Ticket R.6 tests: a fake Anthropic client and answer builders."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

for _name in ("program", "export"):
    _tests = Path(__file__).resolve().parent.parent / _name
    if str(_tests) not in sys.path:
        sys.path.insert(0, str(_tests))


from export_helpers import make_layout, prepare  # noqa: E402, F401

KEY_ENV = "ALE_TEST_CRITIQUE_KEY"


class FakeMessages:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClient:
    """Mimics ``anthropic.Anthropic`` for ``client.beta.messages.create`` only."""

    def __init__(self, *outcomes: Any) -> None:
        self.messages = FakeMessages(list(outcomes))
        self.beta = SimpleNamespace(messages=self.messages)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.messages.calls


def message(
    text: str | None,
    *,
    stop_reason: str = "end_turn",
    blocks: list[Any] | None = None,
    category: str | None = None,
) -> SimpleNamespace:
    content: list[Any] = list(blocks or [])
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    details = SimpleNamespace(type="refusal", category=category) if category else None
    return SimpleNamespace(stop_reason=stop_reason, stop_details=details, content=content)


def answer(*defects: dict[str, Any], summary: str = "Plan correct.") -> str:
    return json.dumps({"defects": list(defects), "summary": summary})


def defect(room_ids: list[str], kind: str = "circulation", severity: int = 2) -> dict[str, Any]:
    return {
        "room_ids": room_ids,
        "kind": kind,
        "severity": severity,
        "observation": "Observation sur " + ", ".join(room_ids or ["le plan"]),
        "suggestion": "Suggestion concrète.",
    }
