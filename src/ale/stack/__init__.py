"""Multi-storey stacking and vertical skeleton (Ticket M.1): groups on floors, one core and one
wet stack on identical cells, a cell diagram per floor."""

from __future__ import annotations

from ale.stack.assign import Problem, Score, Stacking, build_problem, derive_groups, solve
from ale.stack.building import Building, dump_building, load_building, parse_building
from ale.stack.floors import FloorResult, stackability
from ale.stack.report import StackResult, render_markdown, render_svg, run_stack, write_outputs
from ale.stack.rules import WET_TYPES, StackInputError, StackRules, load_rules, parse_rules
from ale.stack.skeleton import Skeleton, build_skeleton

__all__ = [
    "WET_TYPES",
    "Building",
    "FloorResult",
    "Problem",
    "Score",
    "Skeleton",
    "StackInputError",
    "StackResult",
    "StackRules",
    "Stacking",
    "build_problem",
    "build_skeleton",
    "derive_groups",
    "dump_building",
    "load_building",
    "load_rules",
    "parse_building",
    "parse_rules",
    "render_markdown",
    "render_svg",
    "run_stack",
    "solve",
    "stackability",
    "write_outputs",
]
