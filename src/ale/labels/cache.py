"""On-disk cache of raw VLM responses (``workspace/cache/vlm/``).

Key = sha256 of (``source_sha256``, page, plan_index, prompt version, model id,
sha256(image)). The value is the provider's raw response text, stored as UTF-8 in
``<key>.txt``. Writes are atomic (temporary file + ``os.replace``), which is also safe on
Windows. Cache problems never raise: a read error is a miss, a write error is reported.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ale.workspace import Workspace

__all__ = ["VlmCache", "cache_key"]

_KEY_HEX = frozenset("0123456789abcdef")


def cache_key(
    *,
    source_sha256: str,
    page: int,
    plan_index: int,
    prompt_version: str,
    model_id: str,
    image: bytes,
) -> str:
    """Hex sha256 cache key of one VLM call."""
    parts = [
        source_sha256,
        page,
        plan_index,
        prompt_version,
        model_id,
        hashlib.sha256(image).hexdigest(),
    ]
    payload = json.dumps(parts, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class VlmCache:
    """A directory of cached raw VLM responses."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    @classmethod
    def for_workspace(cls, workspace: Workspace) -> VlmCache:
        """The cache of a workspace (``<root>/cache/vlm``)."""
        return cls(workspace.path("cache", "vlm"))

    def _file(self, key: str) -> Path:
        if len(key) != 64 or not set(key) <= _KEY_HEX:
            raise ValueError(f"invalid cache key {key!r}")
        return self.directory / f"{key}.txt"

    def get(self, key: str) -> str | None:
        """The cached raw response, or ``None`` (miss, bad key or unreadable file)."""
        try:
            return self._file(key).read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None

    def put(self, key: str, raw: str) -> str | None:
        """Store ``raw`` under ``key``; returns an error message instead of raising."""
        try:
            target = self._file(key)
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".tmp-", suffix=".txt")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                    fh.write(raw)
                Path(tmp).replace(target)
            except BaseException:
                with contextlib.suppress(OSError):
                    Path(tmp).unlink()
                raise
        except (OSError, ValueError) as exc:
            return f"VLM cache write failed: {exc}"
        return None
