"""Ticket 0.4 eval section 3: shared fixtures (F01-F07)."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest
from fixtures import (
    DATA_DIR,
    FIXTURE_PAIRS,
    FakeClock,
    load_program,
    load_site,
)

from ale.config import AleConfig
from ale.contracts.geometry import to_shapely
from ale.contracts.models import Program, SiteSpec
from ale.contracts.taxonomy import Taxonomy
from ale.contracts.units import Rounding, m_to_modules
from ale.workspace import Workspace, is_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_FIXTURES = REPO_ROOT / "specs" / "tickets" / "0.4_guards-harness" / "fixtures"

ALLOWED_TYPES = {
    "office",
    "open_office",
    "meeting_room",
    "entrance_hall",
    "reception",
    "sanitary",
    "sanitary_accessible",
    "storage",
    "technical_room",
    "it_room",
    "kitchenette",
    "stair",
    "lift",
}


def net_area(program: Program) -> float:
    return sum(room.target_area_m2 * room.quantity for room in program.rooms)


def footprint_area(site: SiteSpec) -> float:
    return float(to_shapely(site.footprint).area)


@pytest.fixture
def programs(program_8: Program, program_25: Program, program_60: Program) -> dict[str, Program]:
    return {"program_08": program_8, "program_25": program_25, "program_60": program_60}


@pytest.fixture
def sites(site_rect_small: SiteSpec, site_rect: SiteSpec, site_l: SiteSpec) -> dict[str, SiteSpec]:
    return {"site_rect_small": site_rect_small, "site_rect": site_rect, "site_L": site_l}


def test_F01_verbatim() -> None:
    spec_files = sorted(p.name for p in SPEC_FIXTURES.glob("*.yaml"))
    data_files = sorted(p.name for p in DATA_DIR.glob("*.yaml"))
    assert len(spec_files) == 6
    assert data_files == spec_files
    for name in spec_files:
        assert (DATA_DIR / name).read_bytes() == (SPEC_FIXTURES / name).read_bytes(), name


@pytest.mark.parametrize(
    ("name", "n_instances", "net_m2"),
    [("program_08", 8, 75.0), ("program_25", 25, 334.0), ("program_60", 60, 962.0)],
)
def test_F02_programs_valid(
    programs: dict[str, Program], name: str, n_instances: int, net_m2: float
) -> None:
    program = programs[name]
    assert isinstance(program, Program)
    assert len(program.instances()) == n_instances
    assert net_area(program) == pytest.approx(net_m2, abs=1e-9)
    assert load_program(name) == program  # type: ignore[arg-type]


def test_F03_types_covered(programs: dict[str, Program], taxonomy: Taxonomy) -> None:
    used = {room.type for program in programs.values() for room in program.rooms}
    assert used <= ALLOWED_TYPES, used - ALLOWED_TYPES
    assert used <= set(taxonomy.keys())


@pytest.mark.parametrize(
    ("name", "area_m2"),
    [("site_rect_small", 100.0), ("site_rect", 432.0), ("site_L", 1224.0)],
)
def test_F04_sites_valid(sites: dict[str, SiteSpec], name: str, area_m2: float) -> None:
    site = sites[name]
    assert isinstance(site, SiteSpec)
    assert footprint_area(site) == pytest.approx(area_m2, abs=1e-9)
    coords = [
        c for ring in (site.footprint.exterior, *site.footprint.holes) for pt in ring for c in pt
    ]
    if site.core_hint is not None:
        coords.extend(site.core_hint)
    for x in coords:
        m_to_modules(x, 100, Rounding.EXACT)  # raises NotOnGridError if off-grid
    assert load_site(name) == site  # type: ignore[arg-type]


def test_F04_site_l_north(site_l: SiteSpec) -> None:
    assert site_l.north_angle_deg == 20.0


@pytest.mark.parametrize("pair_index", [0, 1, 2])
def test_F05_feasibility_intent(
    fixture_pairs: tuple[tuple[str, str], ...],
    programs: dict[str, Program],
    sites: dict[str, SiteSpec],
    default_config: AleConfig,
    pair_index: int,
) -> None:
    expected_fill = (0.899, 0.923, 0.936)[pair_index]
    program_name, site_name = fixture_pairs[pair_index]
    program, site = programs[program_name], sites[site_name]
    n_instances = len(program.instances())
    left = net_area(program) * (1 + default_config.circulation.ratio) + 0.18 * n_instances
    area = footprint_area(site)
    assert left <= area * default_config.site.max_fill
    assert left / area == pytest.approx(expected_fill, abs=0.001)


def test_F05_fixture_pairs_value(fixture_pairs: tuple[tuple[str, str], ...]) -> None:
    assert fixture_pairs == (
        ("program_08", "site_rect_small"),
        ("program_25", "site_rect"),
        ("program_60", "site_L"),
    )
    assert fixture_pairs == FIXTURE_PAIRS


_SEEN_WORKSPACES: list[Path] = []


@pytest.mark.parametrize("run", [1, 2])
def test_F06_tmp_workspace(tmp_workspace: Workspace, run: int) -> None:
    root = tmp_workspace.root
    assert isinstance(tmp_workspace, Workspace)
    assert is_workspace(root)
    assert root.is_dir()
    assert unicodedata.normalize("NFC", "ws é") in unicodedata.normalize("NFC", str(root))
    assert root.name == "ws é"
    assert isinstance(tmp_workspace.config, AleConfig)
    for previous in _SEEN_WORKSPACES:
        assert previous != root
        assert not previous.exists() or not previous.samefile(root)
    _SEEN_WORKSPACES.append(root)


def test_F07_fake_clock(fake_clock: FakeClock) -> None:
    assert fake_clock() == 1000.0
    fake_clock.advance(2.5)
    assert fake_clock() == 1002.5
    with pytest.raises(ValueError):
        fake_clock.advance(-1.0)


def test_loaders_reject_unknown_names() -> None:
    with pytest.raises(ValueError):
        load_program("program_99")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        load_site("site_X")  # type: ignore[arg-type]
