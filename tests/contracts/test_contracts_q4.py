"""Ticket Q.4 eval D01: contract amendment 1.4.0, ``FacadeConfig.max_depth_m``."""

from __future__ import annotations

import json
import tomllib

import pytest
from pydantic import ValidationError

from ale.contracts import config as config_mod
from ale.contracts import export_schemas, lock
from ale.contracts.config import AleConfig, FacadeConfig
from ale.contracts.version import CONTRACTS_VERSION

OLD_TOML = """
[grid]
module_mm = 600

[facade]
min_facade_len_m = 2.4

[area]
tol_down_pct = 0
tol_up_pct = 10
tol_up_abs_m2 = 0
"""


def test_D01_contract() -> None:
    assert CONTRACTS_VERSION == "1.4.0"
    # Default None (rule off); old configs load unchanged.
    assert FacadeConfig().max_depth_m is None
    assert AleConfig().facade.max_depth_m is None
    old = AleConfig.model_validate(tomllib.loads(OLD_TOML))
    assert old.facade == FacadeConfig(min_facade_len_m=2.4)
    assert old.facade.max_depth_m is None
    # Setting it, and its validation (positive).
    on = AleConfig.model_validate({"facade": {"max_depth_m": 7.2}})
    assert on.facade.max_depth_m == 7.2
    for bad in (0.0, -1.0, "deep"):
        with pytest.raises(ValidationError):
            AleConfig.model_validate({"facade": {"max_depth_m": bad}})
    with pytest.raises(ValidationError):  # still extra="forbid"
        AleConfig.model_validate({"facade": {"max_depth": 7.2}})
    # Schemas regenerated, lock in sync.
    schema = json.loads(config_mod.schema_path().read_text(encoding="utf-8"))
    assert schema == json.loads(config_mod.schema_text())
    prop = schema["$defs"]["FacadeConfig"]["properties"]["max_depth_m"]
    assert prop["default"] is None
    assert {"type": "null"} in prop["anyOf"]
    assert "FACADE_DEPTH" in prop["description"]
    # Scope change: the limit is soft unless ``max_depth_hard``; its cost weight.
    assert FacadeConfig().max_depth_hard is False and old.facade.max_depth_hard is False
    assert on.facade.max_depth_hard is False
    hard = AleConfig.model_validate({"facade": {"max_depth_m": 7.2, "max_depth_hard": True}})
    assert hard.facade.max_depth_hard is True
    assert schema["$defs"]["FacadeConfig"]["properties"]["max_depth_hard"]["default"] is False
    assert AleConfig().optimizer.weights.facade_depth == 1.0
    assert old.optimizer.weights == AleConfig().optimizer.weights
    with pytest.raises(ValidationError):
        AleConfig.model_validate({"optimizer": {"weights": {"facade_depth": -1.0}}})
    weights = schema["$defs"]["OptimizerWeightsConfig"]["properties"]
    assert weights["facade_depth"]["default"] == 1.0
    assert export_schemas.main(["--check"]) == 0
    assert lock.main(["--check"]) == 0
