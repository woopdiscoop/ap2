"""Frozen configuration contract: the ``ale.toml`` model tree (RD 0.1 section 6).

Every table of ``ale.toml`` maps to one sub-model; field names are the TOML keys.
All tables and keys are optional in the file and take the defaults below.

Regenerate the committed JSON schema with::

    python -m ale.contracts.config --write-schema
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_FILENAME = "config.schema.json"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkspaceConfig(_Section):
    format_version: Literal[1] = Field(1, description="Workspace format version, must be 1.")


class GridConfig(_Section):
    module_mm: int = Field(
        100, ge=100, le=1200, description="1 module = module_mm millimetres (U-1: 0.10 m)."
    )


class AreaConfig(_Section):
    tol_down_pct: float = Field(3.0, ge=0.0, le=20.0, description="Allowed undershoot, percent.")
    tol_up_pct: float = Field(3.0, ge=0.0, le=20.0, description="Allowed overshoot, percent.")
    tol_up_abs_m2: float = Field(
        1.2, ge=0.0, le=10.0, description="Allowed absolute overshoot, square metres."
    )


class ShapeConfig(_Section):
    aspect_max: float = Field(
        2.0,
        ge=1.0,
        le=6.0,
        description="Hard limit long side / short side for every room; circulation is exempt.",
    )


class CirculationConfig(_Section):
    ratio: float = Field(0.18, ge=0.05, le=0.5, description="Circulation share (open).")
    min_door_edge_m: float = Field(1.2, gt=0.0, description="Minimum door edge, metres.")
    min_width_m: float = Field(1.2, gt=0.0, description="Corridor clear width, metres (U-3).")


class FacadeConfig(_Section):
    min_facade_len_m: float = Field(2.4, gt=0.0, description="Minimum facade length, metres.")
    max_depth_m: float | None = Field(
        None,
        gt=0.0,
        description=(
            "Maximum depth from the facade of a needs_facade room, metres (contracts 1.4.0); "
            "unset = rule off. A room with exterior contact on two opposite sides may be twice "
            "as deep. Violations are reported as FACADE_DEPTH (hard)."
        ),
    )


class SiteConfig(_Section):
    max_fill: float = Field(0.95, ge=0.5, le=1.0, description="Feasibility check fill ratio.")


class DeterminismConfig(_Section):
    seed: int = Field(42, ge=0, description="Default for `ale generate --seed`.")


class ToolsConfig(_Section):
    oda_file_converter: str = Field("", description='ODA File Converter path; "" = auto-detect.')
    accoreconsole: str = Field("", description='AutoCAD accoreconsole path; "" = auto-detect.')
    timeout_s: float = Field(300.0, gt=0.0, description="Per external process call, seconds.")


class VlmConfig(_Section):
    provider: str = Field("", description='VLM provider (open); "" = VLM disabled.')
    model_id: str = Field("", description="VLM model id (open).")
    api_key_env: str = Field(
        "ALE_VLM_API_KEY", description="Name of the env var holding the key, never the key."
    )
    temperature: float = Field(0.0, description="Must equal 0.0.")
    prompt_version: str = Field("v1", description="Prompt version.")
    max_invalid_json_retries: int = Field(1, ge=0, le=3, description="Retries on invalid JSON.")
    timeout_s: float = Field(120.0, gt=0.0, description="Per VLM call, seconds.")

    @field_validator("temperature")
    @classmethod
    def _temperature_is_zero(cls, value: float) -> float:
        if value != 0.0:
            raise ValueError("temperature must equal 0.0 (deterministic extraction)")
        return value


class ExtractConfig(_Section):
    raster_dpi: int = Field(300, ge=72, le=1200, description="Raster rendering DPI.")
    pdf_vector_min_paths: int = Field(200, ge=1, description="N in the vector/scanned PDF rule.")
    review_confidence: float = Field(
        0.6, ge=0.0, le=1.0, description="Below this confidence an item goes to `ale review`."
    )


class FidelityWeightsConfig(_Section):
    CAD: float = Field(1.0, ge=0.0, le=1.0, description="Weight of CAD sources.")
    PDF_VECTOR: float = Field(0.8, ge=0.0, le=1.0, description="Weight of vector PDF sources.")
    RASTER: float = Field(0.5, ge=0.0, le=1.0, description="Weight of raster sources.")


class RulebookConfig(_Section):
    min_support: int = Field(5, ge=1, description="Minimum support of a rule.")
    blend_k: float = Field(10.0, gt=0.0, description="Seed pseudo-count.")
    laplace_alpha: float = Field(1.0, ge=0.0, description="Laplace smoothing alpha.")
    fidelity_weights: FidelityWeightsConfig = Field(default_factory=FidelityWeightsConfig)


class OptimizerWeightsConfig(_Section):
    required_adjacency: float = Field(1000.0, ge=0.0)
    rulebook_adjacency: float = Field(1.0, ge=0.0)
    aspect: float = Field(1.0, ge=0.0)
    area_overshoot: float = Field(1.0, ge=0.0)
    facade_orientation: float = Field(1.0, ge=0.0)
    core_distance: float = Field(1.0, ge=0.0)
    circulation_length: float = Field(1.0, ge=0.0)


class OptimizerConfig(_Section):
    max_iter: int = Field(200000, ge=1, description="Maximum iterations.")
    time_budget_s: float = Field(120.0, gt=0.0, description="Time budget, seconds.")
    initial_acceptance: float = Field(
        0.8, ge=0.0, le=1.0, description="Share of uphill moves accepted at T0."
    )
    cooling: float = Field(0.95, gt=0.0, lt=1.0, description="Cooling factor, 0..1 exclusive.")
    moves_per_temperature: int = Field(200, ge=1, description="Moves per temperature step.")
    weights: OptimizerWeightsConfig = Field(default_factory=OptimizerWeightsConfig)


class LoggingConfig(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        "INFO", description="Console log level."
    )


class AleConfig(_Section):
    """Root of ``ale.toml``."""

    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    grid: GridConfig = Field(default_factory=GridConfig)
    area: AreaConfig = Field(default_factory=AreaConfig)
    shape: ShapeConfig = Field(default_factory=ShapeConfig)
    circulation: CirculationConfig = Field(default_factory=CirculationConfig)
    facade: FacadeConfig = Field(default_factory=FacadeConfig)
    site: SiteConfig = Field(default_factory=SiteConfig)
    determinism: DeterminismConfig = Field(default_factory=DeterminismConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    vlm: VlmConfig = Field(default_factory=VlmConfig)
    extract: ExtractConfig = Field(default_factory=ExtractConfig)
    rulebook: RulebookConfig = Field(default_factory=RulebookConfig)
    optimizer: OptimizerConfig = Field(default_factory=OptimizerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def schema_text() -> str:
    """The canonical serialisation of the JSON schema (as committed)."""
    schema: dict[str, Any] = AleConfig.model_json_schema()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def schema_path() -> Path:
    return Path(__file__).with_name(SCHEMA_FILENAME)


def write_schema(target: Path | None = None) -> Path:
    path = target if target is not None else schema_path()
    path.write_text(schema_text(), encoding="utf-8", newline="\n")
    return path


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ale.contracts.config")
    parser.add_argument(
        "--write-schema", action="store_true", required=True, help=f"write {SCHEMA_FILENAME}"
    )
    parser.parse_args(argv)
    write_schema()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
