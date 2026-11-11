"""The ``ale`` command-line interface (typer app and command registration)."""

from __future__ import annotations

import enum
import io
import sys
from typing import Annotated

import typer

from ale import __version__
from ale.cli.commands import critique as critique_cmd
from ale.cli.commands import doctor, extract, form, generate, ingest, init, layers, review, rulebook
from ale.cli.commands import program as program_cmd
from ale.cli.commands import score as score_cmd
from ale.cli.commands import status as status_cmd
from ale.cli.commands import ui as ui_cmd
from ale.cli.commands._common import LOG_LEVEL_EXPLICIT_KEY
from ale.logging_setup import configure_logging, shutdown_logging

__all__ = ["app", "main"]


class LogLevel(enum.StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


app = typer.Typer(
    name="ale",
    help="ALE - Architectural Layout Engine.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)


def _reconfigure_streams() -> None:
    """Never raise UnicodeEncodeError on a legacy console (e.g. cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    log_level: Annotated[
        LogLevel,
        typer.Option("--log-level", help="Console log level (else [logging].level)."),
    ] = LogLevel.INFO,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show the version."
        ),
    ] = False,
) -> None:
    """ALE - Architectural Layout Engine."""
    _reconfigure_streams()
    source = ctx.get_parameter_source("log_level")
    ctx.meta[LOG_LEVEL_EXPLICIT_KEY] = source is not None and source.name != "DEFAULT"
    configure_logging(log_level.value)
    ctx.call_on_close(shutdown_logging)


app.command("init")(init.init)
app.command("doctor")(doctor.doctor)
app.command("ingest")(ingest.ingest)
app.command("extract")(extract.extract)
app.command("layers")(layers.layers)
app.command("review")(review.review)
app.add_typer(rulebook.app, name="rulebook")
app.add_typer(program_cmd.app, name="program")
app.command("generate")(generate.generate)
app.command("status")(status_cmd.status)
app.command("critique")(critique_cmd.critique)
app.command("score")(score_cmd.score)
app.command("form")(form.form)
app.command("ui")(ui_cmd.ui)


def main() -> None:
    """Console-script entry point (``ale``) and ``python -m ale``."""
    _reconfigure_streams()
    app(prog_name="ale")
