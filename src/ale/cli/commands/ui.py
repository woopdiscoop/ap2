"""``ale ui``: start the local Streamlit interface (Ticket U.1)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from ale.cli.commands._common import EXIT_NOT_IMPLEMENTED, WORKSPACE_ENV

__all__ = ["ui"]


def ui(
    workspace: Annotated[
        Path | None, typer.Option("--workspace", help="Dossier de travail (créé si absent).")
    ] = None,
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="Port local.")] = 8501,
) -> None:
    """Open the local web interface (needs the 'ui' extra)."""
    if importlib.util.find_spec("streamlit") is None:
        typer.echo('installez l\'extra ui : pip install -e ".[ui]"', err=True)
        raise typer.Exit(EXIT_NOT_IMPLEMENTED)
    app = Path(__file__).resolve().parents[2] / "ui" / "app.py"
    env = dict(os.environ)
    if workspace is not None:
        env[WORKSPACE_ENV] = str(workspace)
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app),
        "--server.port",
        str(port),
        "--browser.gatherUsageStats",
        "false",
    ]
    raise typer.Exit(subprocess.call(cmd, env=env))
