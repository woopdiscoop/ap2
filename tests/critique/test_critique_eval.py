"""Ticket R.6 evaluation C601-C608 (client mocked, no network, no real key)."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from critique_helpers import KEY_ENV, FakeClient, answer, defect, message
from typer.testing import CliRunner

from ale.cli import app
from ale.config import AleConfig
from ale.contracts.models import Layout
from ale.critique import (
    LONG_SIDE,
    RESPONSE_SCHEMA,
    Critique,
    CritiqueError,
    CritiqueUnavailableError,
    render_layout,
    run_critique,
)
from ale.labels.providers.anthropic_provider import DEFAULT_MODEL_ID
from ale.workspace import init_workspace

httpx2 = pytest.importorskip("httpx2")
anthropic = pytest.importorskip("anthropic")

KNOWN_ROOM = "R01"
VARIANT_FILES = ("layout.json", "report.md", "preview.svg")


def _config(**vlm: Any) -> AleConfig:
    base = {"provider": "anthropic", "api_key_env": KEY_ENV}
    return AleConfig.model_validate({"vlm": {**base, **vlm}})


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, "sk-ant-test-fake")


def _snapshot(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir()) if p.is_file()}


def _png_size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])  # type: ignore[no-any-return]


# --------------------------------------------------------------------------- C601
def test_C601_request(variant: Path) -> None:
    client = FakeClient(message(answer()))
    run_critique(variant, _config(), client=client)
    assert len(client.calls) == 1
    call = client.calls[0]
    content = call["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "text"]
    src = content[0]["source"]
    assert src["media_type"] == "image/png"
    png = base64.b64decode(src["data"])
    w, h = _png_size(png)
    assert max(w, h) <= 1568
    assert max(w, h) == LONG_SIDE
    assert "R03#2" in content[1]["text"]  # the table
    fmt = call["output_config"]["format"]
    assert fmt == {"type": "json_schema", "schema": RESPONSE_SCHEMA}
    item = RESPONSE_SCHEMA["properties"]["defects"]["items"]  # type: ignore[index]
    assert set(item["required"]) == {"room_ids", "kind", "severity", "observation", "suggestion"}
    assert item["properties"]["kind"]["enum"] == [
        "circulation",
        "lumiere",
        "proportion",
        "adjacence",
        "acces",
        "residuel",
        "autre",
    ]
    assert item["properties"]["severity"]["enum"] == [1, 2, 3]
    assert call["output_config"]["effort"] == "low"
    assert call["thinking"] == {"type": "adaptive"}
    assert call["fallbacks"] == "default"
    assert call["betas"]
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in call
    assert call["model"] == DEFAULT_MODEL_ID


def test_C601_model_from_config(variant: Path) -> None:
    client = FakeClient(message(answer()))
    run_critique(variant, _config(model_id="claude-custom-1"), client=client)
    assert client.calls[0]["model"] == "claude-custom-1"


# --------------------------------------------------------------------------- C602
def test_C602_outputs(variant: Path) -> None:
    defects = [
        defect(["R01", "R02"], "adjacence", 1),
        defect(["R03#2"], "proportion", 3),
        defect([], "autre", 2),
    ]
    res = run_critique(variant, _config(), client=FakeClient(message(answer(*defects))))
    md = (variant / "critique.md").read_text(encoding="utf-8")
    assert md.count("\n### ") == 3
    assert "Critique visuelle" in md
    assert "`R01`" in md and "`R03#2`" in md
    assert "Adjacences" in md and "gravité 3 sur 3" in md
    crit = Critique.model_validate_json((variant / "critique.json").read_text(encoding="utf-8"))
    assert len(crit.defects) == 3
    assert crit == res.critique
    assert crit.model_id == DEFAULT_MODEL_ID
    # room names from report.md are shown next to the ids
    names = [line for line in md.splitlines() if line.startswith("- Pièces : `R01`")]
    assert names and "(" in names[0]
    # JSON also validates against the answer schema's required keys
    raw = json.loads((variant / "critique.json").read_text(encoding="utf-8"))
    assert set(raw["defects"][0]) == {"room_ids", "kind", "severity", "observation", "suggestion"}


def test_C602_no_defect(variant: Path) -> None:
    run_critique(variant, _config(), client=FakeClient(message(answer())))
    assert "Aucun défaut relevé" in (variant / "critique.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- C603
def test_C603_unknown_ids(variant: Path) -> None:
    defects = [
        defect(["R01", "NOPE", "R01"], "lumiere"),
        defect(["GHOST"], "acces", 3),
    ]
    res = run_critique(variant, _config(), client=FakeClient(message(answer(*defects))))
    crit = res.critique
    assert crit.defects[0].room_ids == ("R01",)
    assert crit.defects[1].room_ids == ()
    assert crit.unknown_room_ids == 2
    assert crit.warnings and "2" in crit.warnings[0]
    md = res.critique_md.read_text(encoding="utf-8")
    assert "Pièces : général" in md
    assert "Avertissements" in md
    assert "`GHOST`" not in md and "`NOPE`" not in md


# --------------------------------------------------------------------------- C604
def test_C604_advisory(variant: Path) -> None:
    before = _snapshot(variant)
    assert set(before) >= {"layout.json", "report.md", "preview.svg"}
    run_critique(variant, _config(), client=FakeClient(message(answer(defect(["R01"])))))
    after = _snapshot(variant)
    for name, data in before.items():
        assert after[name] == data
    assert set(after) - set(before) == {"critique.md", "critique.json"}


# --------------------------------------------------------------------------- C605
def test_C605_cache(variant: Path, tmp_path: Path) -> None:
    cache = tmp_path / "ws" / "cache" / "critique"
    client = FakeClient(message(answer(defect(["R01"]), summary="Synthèse.")))
    first = run_critique(variant, _config(), cache_dir=cache, client=client)
    files1 = {n: (variant / n).read_bytes() for n in ("critique.md", "critique.json")}
    second = run_critique(variant, _config(), cache_dir=cache, client=client)
    assert (first.calls, second.calls) == (1, 0)
    assert len(client.calls) == 1
    for n, data in files1.items():
        assert (variant / n).read_bytes() == data
    # another model id is a different key
    run_critique(variant, _config(model_id="other-model"), cache_dir=cache, client=client)
    assert len(client.calls) == 2


def test_C605_cache_corrupt_entry_recalls(variant: Path, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    client = FakeClient(message(answer()))
    run_critique(variant, _config(), cache_dir=cache, client=client)
    for f in cache.glob("*.txt"):
        f.write_text("not json", encoding="utf-8")
    res = run_critique(variant, _config(), cache_dir=cache, client=client)
    assert res.calls == 1


# --------------------------------------------------------------------------- C606
def test_C606_no_provider(variant: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = _snapshot(variant)
    for cfg in (_config(provider=""), _config(provider="other")):
        with pytest.raises(CritiqueUnavailableError, match=r"\[vlm\]"):
            run_critique(variant, cfg, client=FakeClient(message(answer())))
    monkeypatch.delenv(KEY_ENV)
    with pytest.raises(CritiqueUnavailableError, match="clé d'API"):
        run_critique(variant, _config(), client=FakeClient(message(answer())))
    assert _snapshot(variant) == before


def _cli_workspace(tmp_path: Path, provider: str, name: str = "ws") -> Path:
    root, _ = init_workspace(tmp_path / name)
    toml = root / "ale.toml"
    text = toml.read_text(encoding="utf-8")
    text = text.replace('provider = ""', f'provider = "{provider}"', 1)
    text = text.replace('api_key_env = "ALE_VLM_API_KEY"', f'api_key_env = "{KEY_ENV}"', 1)
    toml.write_text(text, encoding="utf-8")
    return root


def test_C606_cli_exit_3(variant: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = _snapshot(variant)
    runner = CliRunner()
    ws = _cli_workspace(tmp_path, "")
    res = runner.invoke(app, ["critique", "--variant", str(variant), "--workspace", str(ws)])
    assert res.exit_code == 3
    assert "[vlm]" in res.stderr and "fournisseur" in res.stderr
    # default config (no workspace) is also "no provider"
    res = runner.invoke(app, ["critique", "--variant", str(variant)])
    assert res.exit_code == 3
    # provider set, key unset
    root = _cli_workspace(tmp_path, "anthropic", "ws2")
    monkeypatch.delenv(KEY_ENV)
    res = runner.invoke(app, ["critique", "--variant", str(variant), "--workspace", str(root)])
    assert res.exit_code == 3
    assert "clé d'API" in res.stderr
    assert _snapshot(variant) == before


# --------------------------------------------------------------------------- C607
def _status(cls: type[Exception], status: int) -> Exception:
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(status, request=req), body=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "outcome",
    [
        message(None, stop_reason="refusal", category="cyber"),
        message(None, stop_reason="refusal"),
        message("{}", stop_reason="max_tokens"),
        message("{}", stop_reason="weird"),
        message(None),
        message("pas du json"),
        message(json.dumps({"defects": [defect(["R01"], "inconnu")], "summary": "x"})),
        _status(anthropic.RateLimitError, 429),
        anthropic.APITimeoutError(request=httpx2.Request("POST", "https://x.invalid")),
        anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x.invalid")),
    ],
)
def test_C607_refusal_error(variant: Path, outcome: Any) -> None:
    before = _snapshot(variant)
    with pytest.raises(CritiqueError) as ei:
        run_critique(variant, _config(), client=FakeClient(outcome))
    assert not isinstance(ei.value, CritiqueUnavailableError)
    assert _snapshot(variant) == before


def test_C607_cli_exit_1(variant: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ale.critique.critic as critic

    before = _snapshot(variant)
    ws = _cli_workspace(tmp_path, "anthropic")
    client = FakeClient(message(None, stop_reason="refusal", category="cyber"))
    monkeypatch.setattr(critic, "_make_client", lambda config: client)
    res = CliRunner().invoke(app, ["critique", "--variant", str(variant), "--workspace", str(ws)])
    assert res.exit_code == 1
    assert "refusé" in res.stderr
    assert _snapshot(variant) == before
    assert not list((ws / "cache" / "critique").glob("*"))


def test_C607_unreadable_variant(tmp_path: Path) -> None:
    (tmp_path / "v").mkdir()
    with pytest.raises(CritiqueError, match="illisible"):
        run_critique(tmp_path / "v", _config(), client=FakeClient(message(answer())))
    (tmp_path / "v" / "layout.json").write_text("{}", encoding="utf-8")
    (tmp_path / "v" / "report.md").write_text("", encoding="utf-8")
    with pytest.raises(CritiqueError, match="plan valide"):
        run_critique(tmp_path / "v", _config(), client=FakeClient(message(answer())))


def test_C607_cli_success_and_json(
    variant: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ale.critique.critic as critic

    ws = _cli_workspace(tmp_path, "anthropic")
    client = FakeClient(message(answer(defect(["R01", "ZZ"]))))
    monkeypatch.setattr(critic, "_make_client", lambda config: client)
    args = ["critique", "--variant", str(variant), "--workspace", str(ws)]
    res = CliRunner().invoke(app, [*args, "--json"])
    assert res.exit_code == 0
    assert json.loads(res.stdout)["unknown_room_ids"] == 1
    assert "Avertissement" in res.stderr
    res = CliRunner().invoke(app, args)
    assert res.exit_code == 0
    assert "cache" in res.stderr + res.stdout
    assert len(client.calls) == 1


def test_C607_make_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import ale.critique.critic as critic

    made: dict[str, Any] = {}

    class Fake:
        def __init__(self, **kw: Any) -> None:
            made.update(kw)

    monkeypatch.setattr(anthropic, "Anthropic", Fake)
    critic._make_client(_config(timeout_s=7.0))
    assert made["api_key"] == "sk-ant-test-fake" and made["timeout"] == 7.0


def test_C607_fallback_block_text_only_final(variant: Path) -> None:
    blocks = [
        SimpleNamespace(type="text", text="PARTIEL"),
        SimpleNamespace(type="fallback"),
    ]
    res = run_critique(variant, _config(), client=FakeClient(message(answer(), blocks=blocks)))
    assert res.critique.defects == ()


# --------------------------------------------------------------------------- C608
def test_C608_render(layout: Layout) -> None:
    r1 = render_layout(layout)
    r2 = render_layout(layout)
    assert r1.png == r2.png
    assert max(r1.size) == LONG_SIDE
    assert _png_size(r1.png) == r1.size
    ids = {p.instance_id for p in (*layout.rooms, *layout.circulation)}
    assert set(r1.label_boxes) == ids == set(r1.room_boxes)
    for iid, (lx0, ly0, lx1, ly1) in r1.label_boxes.items():
        rx0, ry0, rx1, ry1 = r1.room_boxes[iid]
        assert lx0 < lx1 and ly0 < ly1
        assert rx0 <= lx0 and ry0 <= ly0 and lx1 <= rx1 and ly1 <= ry1, iid


def test_C608_render_pixels(layout: Layout) -> None:
    from PIL import Image

    from ale.contracts.enums import MacroZone
    from ale.export.svg import ZONE_COLOURS

    zone = next(iter(MacroZone))
    r = render_layout(layout, {"R01": zone}, north_angle_deg=45.0)
    img = Image.open(io.BytesIO(r.png)).convert("RGB")
    x0, y0, *_ = r.room_boxes["R01"]
    h = ZONE_COLOURS[zone].lstrip("#")
    want = tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
    assert img.getpixel((x0 + 6, y0 + 6)) == want
    assert render_layout(layout, {}, north_angle_deg=45.0).png != r.png
    assert render_layout(layout, north_angle_deg=90.0).png != render_layout(layout).png


def test_C608_cache_key_stable() -> None:
    from ale.critique.critic import cache_key

    k = cache_key(layout_sha256="a", prompt_version="v", model_id="m")
    assert k == cache_key(layout_sha256="a", prompt_version="v", model_id="m")
    assert k != cache_key(layout_sha256="b", prompt_version="v", model_id="m")
    assert hashlib.sha256(b"").hexdigest() != k


# --------------------------------------------------------------------------- C609
def test_C609_gates() -> None:
    """The contract lock still holds (ruff / mypy / coverage are run as gates)."""
    import subprocess
    import sys

    res = subprocess.run(
        [sys.executable, "-m", "ale.contracts.lock", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
