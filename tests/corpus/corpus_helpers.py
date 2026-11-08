"""Fixture builders for the Ticket 1.1 tests: tiny files generated in the test, never a
real corpus. Pure bytes unless the optional library is installed (ezdxf / PyMuPDF)."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sqlite3
import struct
import zlib
from collections.abc import Callable, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from typer.testing import Result

from ale.workspace import Workspace, open_workspace

Invoke = Callable[[Sequence[object]], Result]

HAS_FITZ = importlib.util.find_spec("pymupdf") is not None
HAS_EZDXF = importlib.util.find_spec("ezdxf") is not None


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def png_bytes(width: int = 2, height: int = 2, shade: int = 0) -> bytes:
    """A valid greyscale PNG."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([shade % 256]) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


def jpeg_bytes() -> bytes:
    """Minimal JPEG framing (SOI, APP0/JFIF, EOI): enough for content detection."""
    app0 = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", len(app0) + 2) + app0 + b"\xff\xd9"


def tiff_bytes() -> bytes:
    """Little-endian TIFF header with an empty IFD at offset 8."""
    return b"II*\x00" + struct.pack("<I", 8) + b"\x00\x00" + b"\x00\x00\x00\x00"


def dxf_bytes() -> bytes:
    """A DXF drawing (ezdxf when installed, else a hand-written minimal file)."""
    if HAS_EZDXF:
        import io

        import ezdxf

        doc = ezdxf.new()
        doc.modelspace().add_line((0, 0), (10, 0))
        stream = io.StringIO()
        doc.write(stream)
        return stream.getvalue().encode("utf-8")
    return b"  0\nSECTION\n  2\nHEADER\n  0\nENDSEC\n  0\nEOF\n"


def dwg_bytes(version: bytes = b"AC1032") -> bytes:
    return version + bytes(128)


def pdf_three_pages() -> bytes:
    """Page 0: 300 line paths; page 1: one full-page image; page 2: blank."""
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    for i in range(300):
        page.draw_line((10, 1 + i * 0.9), (390, 1 + i * 0.9))
    page = doc.new_page(width=400, height=300)
    page.insert_image(page.rect, stream=png_bytes(8, 8, 128), keep_proportion=False)
    doc.new_page(width=400, height=300)
    data: bytes = doc.tobytes()
    doc.close()
    return data


def pdf_one_page(lines: int = 1) -> bytes:
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    for i in range(lines):
        page.draw_line((10, 10 + i), (190, 10 + i))
    data: bytes = doc.tobytes()
    doc.close()
    return data


def encrypted_pdf() -> bytes:
    import pymupdf as fitz

    doc = fitz.open()
    doc.new_page()
    data: bytes = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    doc.close()
    return data


def fake_pdf_bytes() -> bytes:
    """``%PDF-`` content that is not a parseable PDF (used without PyMuPDF too)."""
    return b"%PDF-1.7\n% not really a pdf\n"


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def snapshot(root: Path) -> dict[str, tuple[Any, ...]]:
    """(kind, size, mtime_ns, sha256) of every entry under ``root`` (hidden included)."""
    result: dict[str, tuple[Any, ...]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            p = Path(dirpath) / name
            result[p.relative_to(root).as_posix()] = ("dir",)
        for name in filenames:
            p = Path(dirpath) / name
            st = p.stat()
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            result[p.relative_to(root).as_posix()] = ("file", st.st_size, st.st_mtime_ns, digest)
    return result


def query(db: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(db)) as conn:
        return [tuple(r) for r in conn.execute(sql, params).fetchall()]


def units_of(db: Path, rel_path: str) -> list[tuple[int, str, str, str | None]]:
    """(page, kind, status, reason) of the units of the file at ``rel_path``."""
    return [
        (int(r[0]), str(r[1]), str(r[2]), r[3])
        for r in query(
            db,
            "SELECT u.page, u.kind, u.status, u.reason FROM units u "
            "JOIN file_paths p ON p.sha256 = u.sha256 WHERE p.rel_path = ? ORDER BY u.page",
            (rel_path,),
        )
    ]


def events(db: Path, event: str) -> list[tuple[Any, ...]]:
    return query(db, "SELECT sha256, page, detail FROM events WHERE event = ?", (event,))


def count(db: Path, table: str) -> int:
    return int(query(db, f"SELECT COUNT(*) FROM {table}")[0][0])


def set_config(ws: Workspace, section: str, key: str, value: str) -> Workspace:
    """Set ``key`` in ``[section]`` of ``ale.toml``; returns the re-opened workspace."""
    path = ws.path("ale.toml")
    lines = path.read_text(encoding="utf-8").splitlines()
    current = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            current = stripped.strip("[]")
        elif current == section and stripped.split("=")[0].strip() == key:
            lines[i] = f"{key} = {value}"
            break
    else:  # pragma: no cover - test helper misuse
        raise KeyError(f"{section}.{key}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return open_workspace(ws.root)
