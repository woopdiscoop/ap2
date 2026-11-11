"""Streamlit app of the local interface (Ticket U.1), in French.

Run with ``ale ui`` (or ``streamlit run`` on this file). All work is done by the same
functions as the CLI commands; see :mod:`ale.ui.core`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import streamlit as st

from ale.config import AleConfig
from ale.ui import core
from ale.ui.core import UiError
from ale.workspace import Workspace

T = TypeVar("T")


def _try(fn: Callable[[], T]) -> T | None:
    """Run ``fn``; show any error in French and keep the app alive."""
    try:
        return fn()
    except UiError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Erreur : {exc}")
    return None


def _sidebar() -> tuple[Workspace, AleConfig, Path | None]:
    st.sidebar.header("Réglages")
    path = st.sidebar.text_input(
        "Dossier de travail",
        value=os.environ.get("ALE_WORKSPACE", "ale_workspace"),
        key="workspace",
    )
    module = st.sidebar.selectbox(
        "Module (m)",
        [0.10, 0.60],
        key="module_m",
        format_func=lambda v: f"{v:.2f}".replace(".", ","),
    )
    never_below = st.sidebar.checkbox(
        "Jamais en dessous du programme (-0 / +10 % de surface)", value=False, key="never_below"
    )
    budget = st.sidebar.number_input(
        "Temps par variante (s)", min_value=1.0, max_value=3600.0, value=30.0, key="budget_s"
    )
    rb_file = st.sidebar.file_uploader(
        "Règles (rulebook .yaml)", type=["yaml", "yml"], key="rulebook_file"
    )
    ws = core.ensure_workspace(path)
    config = core.build_config(
        ws.config,
        module_mm=round(float(module) * 1000),
        never_below=never_below,
        budget_s=float(budget),
    )
    rulebook: Path | None
    if rb_file is not None:
        rulebook = core.save_upload(ws.path("ui", "inputs"), rb_file.name, rb_file.getvalue())
    else:
        rulebook = core.default_rulebook(ws)
        if rulebook is None:
            st.sidebar.warning("Aucune règle trouvée : téléversez un rulebook.")
        else:
            st.sidebar.caption(f"Règles : {rulebook.name} (provisoires).")
    return ws, config, rulebook


# ------------------------------------------------------------------ Programme
def _page_programme(ws: Workspace, rulebook: Path | None, config: AleConfig) -> None:
    from ale.program import read_program
    from ale.program.annexe import AnnexeError, fold_name, load_rules, read_annexe, write_outputs

    st.subheader("Programme")
    kind = st.radio(
        "Type de fichier",
        ["Annexe (programme physique)", "Modèle ALE"],
        key="prog_kind",
        horizontal=True,
    )
    up = st.file_uploader("Fichier .xlsx", type=["xlsx"], key="prog_file")
    rules_up = None
    if kind.startswith("Annexe"):
        with st.expander("Règles de correspondance (optionnel)"):
            rules_up = st.file_uploader("Règles YAML", type=["yaml", "yml"], key="prog_rules")
    if up is None:
        st.info("Téléversez une Annexe ou un modèle ALE.")
        return
    inputs = ws.path("ui", "inputs")
    src = core.save_upload(inputs, up.name, up.getvalue())

    def load() -> tuple[Any, bytes, str]:
        if kind.startswith("Annexe"):
            rules = None
            if rules_up is not None:
                rules = load_rules(core.save_upload(inputs, rules_up.name, rules_up.getvalue()))
            try:
                result = read_annexe(src, rules)
            except AnnexeError as exc:
                raise UiError(f"Annexe illisible : {exc}") from exc
            if result.unmatched:
                lines = [f"{u.building}, ligne {u.row} : « {u.espace} »" for u in result.unmatched]
                raise UiError(
                    "Espaces sans règle de correspondance : "
                    + " ; ".join(lines)
                    + ". Ajoutez des règles ci-dessus."
                )
            if not result.buildings:
                raise UiError("Aucune ligne de programme importée.")
            names = [b.name for b in result.buildings]
            chosen = st.selectbox("Bâtiment", names, key="building")
            b = next(x for x in result.buildings if fold_name(x.name) == fold_name(chosen))
            for w in result.warnings:
                st.warning(w)
            xlsx = write_outputs([b], ws.path("ui", "annexe", b.slug))[0]
            return b.program(), xlsx.read_bytes(), xlsx.name
        program, report = read_program(src)
        if program is None:
            raise UiError("Programme illisible : " + " ; ".join(i.message for i in report.issues))
        return program, src.read_bytes(), src.name

    loaded = _try(load)
    if loaded is None:
        return
    program, data, name = loaded
    lines, inst, m2 = core.program_totals(program)
    c1, c2, c3 = st.columns(3)
    c1.metric("Lignes", lines)
    c2.metric("Espaces (instances)", inst)
    c3.metric("Surface utile (m²)", f"{m2:.2f}")
    st.dataframe(core.program_table(program))
    saved = core.save_upload(ws.path("ui", "program"), name, data)
    st.session_state["program_path"] = str(saved)
    st.download_button(
        "Télécharger le programme ALE (xlsx)",
        data,
        file_name=name,
        key="dl_program",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    site_path = st.session_state.get("site_path")
    if site_path and rulebook is not None:
        from ale.cli.commands.program import _issue_line
        from ale.program.prepare import check_inputs

        res = _try(lambda: check_inputs(saved, Path(site_path), rulebook, config))
        if res is not None:
            st.markdown("**Contrôle programme / site**")
            for i in res.errors:
                st.error(_issue_line(i).strip())
            for i in res.warnings:
                st.warning(_issue_line(i).strip())
            if res.feasibility is not None:
                f = res.feasibility
                st.write(
                    f"Surface requise {f.required_m2:.2f} m², disponible {f.available_m2:.2f} m², "
                    f"taux de remplissage {f.fill_ratio:.3f}."
                )
            if not res.errors:
                st.success("Contrôle : OK")


# ------------------------------------------------------------------ Site
def _site_form() -> tuple[Any, str] | None:
    shape = st.radio("Forme", ["Rectangle", "L"], key="site_shape", horizontal=True)
    c1, c2 = st.columns(2)
    w1 = c1.number_input("Largeur (m)", 1.0, 500.0, 24.0, key="site_w1")
    d1 = c2.number_input("Profondeur (m)", 1.0, 500.0, 18.0, key="site_d1")
    w2, d2 = w1 / 2, d1 * 1.5
    if shape == "L":
        w2 = c1.number_input("Largeur du 2e rectangle (m)", 1.0, 500.0, 12.0, key="site_w2")
        d2 = c2.number_input("Profondeur du 2e rectangle (m)", 1.0, 500.0, 30.0, key="site_d2")
    north = st.number_input("Angle du nord (°)", 0.0, 359.9, 0.0, key="site_north")
    mode = st.radio(
        "Mode",
        ["footprint", "plot"],
        key="site_mode",
        horizontal=True,
        format_func=lambda m: "Emprise du bâtiment" if m == "footprint" else "Parcelle",
    )
    pts = _try(lambda: core.outline("rect" if shape == "Rectangle" else "L", w1, d1, w2, d2))
    if pts is None:
        return None
    access = st.number_input("Côté d'accès (index)", 0, len(pts) - 1, 0, key="site_access")
    e1, e2 = st.columns(2)
    ex = e1.number_input("Entrée x (m)", 0.0, 500.0, float(w1) / 2, key="site_ex")
    ey = e2.number_input("Entrée y (m)", 0.0, 500.0, 0.0, key="site_ey")
    ncores = int(st.number_input("Noyaux", 0, 10, 0, key="site_ncores"))
    cores: list[tuple[float, float, float, float]] = []
    for i in range(ncores):
        cols = st.columns(4)
        cores.append(
            (
                float(cols[0].number_input("x", 0.0, 500.0, 0.0, key=f"core_{i}_x")),
                float(cols[1].number_input("y", 0.0, 500.0, 0.0, key=f"core_{i}_y")),
                float(cols[2].number_input("l", 0.1, 500.0, 3.0, key=f"core_{i}_l")),
                float(cols[3].number_input("p", 0.1, 500.0, 3.0, key=f"core_{i}_p")),
            )
        )
    setbacks: list[float] | None = None
    if mode == "plot":
        st.caption("Retraits par côté (m)")
        setbacks = [
            float(st.number_input(f"Côté {i}", 0.0, 50.0, 3.0, key=f"setback_{i}"))
            for i in range(len(pts))
        ]
    return _try(
        lambda: core.build_site(
            pts,
            north_angle=float(north),
            access_edge=int(access),
            entrance=(ex, ey),
            cores=cores,
            mode=mode,
            setbacks=setbacks,
        )
    )


def _page_site(ws: Workspace) -> None:
    st.subheader("Site")
    up = st.file_uploader("site.yaml existant", type=["yaml", "yml"], key="site_file")
    result: tuple[Any, str] | None = None
    if up is not None:
        text = up.getvalue().decode("utf-8-sig", errors="replace")
        spec = _try(lambda: core.load_site_yaml(text))
        result = None if spec is None else (spec, text)
    else:
        result = _site_form()
    if result is None:
        return
    spec, text = result
    st.image(core.site_svg(spec))
    if st.session_state.get("site_sig") != text:  # the form changed: it becomes the current site
        path = ws.path("ui", "site", "site.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        st.session_state["site_path"] = str(path)
        st.session_state["site_sig"] = text
    st.download_button("Télécharger site.yaml", text, file_name="site.yaml", key="dl_site")


# ------------------------------------------------------------------ Forme
def _page_form(ws: Workspace) -> None:
    st.subheader("Forme")
    if not core.form_available():
        st.info("Recherche de forme : disponible après la fusion de G.3.")
        return
    from ale.cli.commands.form import form as form_cmd

    n = int(st.number_input("Candidats", 1, 20, 3, key="form_n"))
    court = st.checkbox("Cour", value=False, key="form_court")
    if st.button("Chercher des formes", key="form_run"):
        prog, site = st.session_state.get("program_path"), st.session_state.get("site_path")
        if not prog or not site:
            st.error("Chargez d'abord un programme et un site (mode parcelle).")
        else:
            out = core.new_run_dir(ws, "form")
            if (
                _try(
                    lambda: core.run_cli_function(
                        form_cmd,
                        program=Path(prog),
                        site=Path(site),
                        out=out,
                        candidates=n,
                        courtyard=court,
                    )
                )
                is not None
            ):
                st.session_state["form_dir"] = str(out)
    folder = st.session_state.get("form_dir")
    if not folder:
        return
    out = Path(folder)
    svgs = sorted(out.glob("form_*.svg"))
    st.write(f"{len(svgs)} candidat(s).")
    for svg in svgs:
        st.image(svg.read_text(encoding="utf-8"), caption=svg.stem)
        if st.button(f"Utiliser la forme {svg.stem}", key=f"use_{svg.stem}"):
            yaml_path = svg.with_suffix(".yaml")
            st.session_state["site_path"] = str(yaml_path)
            st.success(f"Forme {svg.stem} chargée comme site courant.")
    md = out / "forms.md"
    if md.is_file():
        st.markdown(md.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ Plans
def _inputs_for_plans(ws: Workspace) -> tuple[Path, Path] | None:
    inputs = ws.path("ui", "inputs")
    pu = st.file_uploader(
        "Programme ALE (.xlsx), sinon celui de l'onglet Programme",
        type=["xlsx"],
        key="plans_program",
    )
    su = st.file_uploader(
        "Site (.yaml), sinon celui de l'onglet Site", type=["yaml", "yml"], key="plans_site"
    )
    prog = core.save_upload(inputs, pu.name, pu.getvalue()) if pu else None
    site = core.save_upload(inputs, su.name, su.getvalue()) if su else None
    if prog is None and st.session_state.get("program_path"):
        prog = Path(st.session_state["program_path"])
    if site is None and st.session_state.get("site_path"):
        site = Path(st.session_state["site_path"])
    if prog is None or site is None:
        st.info("Il faut un programme et un site.")
        return None
    return prog, site


def _page_plans(ws: Workspace, config: AleConfig, rulebook: Path | None) -> None:
    from ale.optimize import generate
    from ale.program.models import InputError

    st.subheader("Plans")
    inputs = _inputs_for_plans(ws)
    nv = int(st.number_input("Variantes", 1, 12, 2, key="n_variants"))
    seed = int(st.number_input("Graine", 0, 10**6, config.determinism.seed, key="seed"))
    if inputs is not None and rulebook is None:
        st.warning("Téléversez un rulebook dans la barre latérale.")
    elif inputs is not None and rulebook is not None and st.button("Générer", key="run_generate"):
        out = core.new_run_dir(ws, "plans")

        def run() -> Any:
            try:
                with st.spinner("Génération en cours…"):
                    return generate(
                        inputs[0], inputs[1], rulebook, out, seed=seed, variants=nv, config=config
                    )
            except InputError as exc:
                errs = [i.message for i in exc.issues if i.severity == "error"]
                raise UiError("Entrées invalides : " + " ; ".join(errs)) from exc
            except FileExistsError as exc:
                raise UiError(f"Échec : {exc}") from exc

        res = _try(run)
        if res is not None:
            st.session_state["plans_dir"] = str(out)
            st.session_state["plans_variants"] = [
                (
                    v.index,
                    str(v.out_dir) if v.out_dir else "",
                    v.status,
                    v.final_cost,
                    v.violations,
                    v.circulation_pct,
                    "; ".join(v.failures),
                )
                for v in res.variants
            ]
    rows = st.session_state.get("plans_variants")
    if not rows:
        return
    st.dataframe(
        [
            {
                "variante": r[0],
                "statut": r[2],
                "coût": r[3],
                "violations": r[4],
                "circulation (%)": r[5],
                "remarque": r[6],
            }
            for r in rows
        ]
    )
    ok = [r for r in rows if r[2] == "ok"]
    for r in rows:
        if r[2] != "ok":
            st.error(f"Variante {r[0]:02d} : échec ({r[6]})")
    if not ok:
        return
    cols = st.columns(len(ok))
    for col, r in zip(cols, ok, strict=True):
        with col:
            col.image(
                Path(r[1], "preview.svg").read_text(encoding="utf-8"),
                caption=f"Variante {r[0]:02d} : violations {r[4]}, coût {r[3]:.3f}",
            )
    choice = st.selectbox("Variante affichée", [r[0] for r in ok], key="sel_variant")
    vdir = Path(next(r[1] for r in ok if r[0] == choice))
    st.session_state["variant_dir"] = str(vdir)
    report = vdir / "report.md"
    if report.is_file():
        st.markdown(report.read_text(encoding="utf-8"))
    for label, fname, key in (
        ("DXF", "layout.dxf", "dl_dxf"),
        ("SVG", "preview.svg", "dl_svg"),
        ("Rapport", "report.md", "dl_report"),
    ):
        f = vdir / fname
        if f.is_file():
            st.download_button(f"Télécharger {label}", f.read_bytes(), file_name=fname, key=key)
    st.download_button(
        "Tout télécharger (zip)",
        core.zip_folder(Path(st.session_state["plans_dir"])),
        file_name="plans.zip",
        key="dl_zip",
    )


# ------------------------------------------------------------------ Score
def _page_score(ws: Workspace) -> None:
    from ale.cli.commands.score import score as score_cmd
    from ale.program.annexe import read_annexe

    st.subheader("Évaluer un projet existant")
    inputs = ws.path("ui", "inputs")
    plan = st.file_uploader(
        "Plan (PDF vectoriel, DXF, DWG)", type=["pdf", "dxf", "dwg"], key="score_plan"
    )
    kind = st.radio("Programme", ["Modèle ALE", "Annexe"], key="score_kind", horizontal=True)
    pf = st.file_uploader("Programme (.xlsx)", type=["xlsx"], key="score_prog")
    page = int(st.number_input("Page du PDF", 1, 999, 1, key="score_page"))
    tol = float(st.number_input("Tolérance (%)", 0.0, 100.0, 5.0, key="score_tol"))
    building: str | None = None
    if pf is not None and kind == "Annexe":
        src = core.save_upload(inputs, pf.name, pf.getvalue())
        res = _try(lambda: read_annexe(src))
        if res is not None and res.buildings:
            building = st.selectbox(
                "Bâtiment", [b.slug for b in res.buildings], key="score_building"
            )
    if st.button("Évaluer", key="run_score"):
        if plan is None or pf is None:
            st.error("Téléversez un plan et un programme.")
            return
        plan_path = core.save_upload(inputs, plan.name, plan.getvalue())
        prog_path = core.save_upload(inputs, pf.name, pf.getvalue())
        out = core.new_run_dir(ws, "score")
        done = _try(
            lambda: core.run_cli_function(
                score_cmd,
                plan=plan_path,
                programme=prog_path if kind == "Modèle ALE" else None,
                annexe=prog_path if kind == "Annexe" else None,
                building=building,
                page=page,
                out=out,
                tolerance_pct=tol,
            )
        )
        if done is not None:
            st.session_state["score_md"] = (out / "score.md").read_text(encoding="utf-8")
    if st.session_state.get("score_md"):
        st.markdown(st.session_state["score_md"])


# ------------------------------------------------------------------ Critique
def _page_critique(ws: Workspace, config: AleConfig) -> None:
    from ale.critique import CritiqueError, CritiqueUnavailableError, run_critique

    st.subheader("Critique")
    vdir = st.session_state.get("variant_dir")
    key_ok = bool(os.environ.get(config.vlm.api_key_env))
    if not config.vlm.provider or not key_ok:
        st.info("Critique indisponible : renseignez [vlm] provider dans ale.toml et la clé API.")
        return
    if not vdir:
        st.info("Générez d'abord des plans et choisissez une variante.")
        return
    if st.button("Critiquer la variante", key="run_critique"):
        try:
            r = run_critique(Path(vdir), config, cache_dir=ws.path("cache", "critique"))
            st.markdown(r.critique_md.read_text(encoding="utf-8"))
        except (CritiqueUnavailableError, CritiqueError) as exc:
            st.error(f"Critique : {exc}")


def main() -> None:
    st.set_page_config(page_title="ALE", layout="wide")
    st.title("ALE : générateur de plans")
    ws_cfg = _try(_sidebar)
    if ws_cfg is None:
        return
    ws, config, rulebook = ws_cfg
    tabs = st.tabs(["Programme", "Site", "Forme", "Plans", "Évaluer", "Critique"])
    pages: list[Callable[[], None]] = [
        lambda: _page_programme(ws, rulebook, config),
        lambda: _page_site(ws),
        lambda: _page_form(ws),
        lambda: _page_plans(ws, config, rulebook),
        lambda: _page_score(ws),
        lambda: _page_critique(ws, config),
    ]
    for tab, page in zip(tabs, pages, strict=True):
        with tab:
            _try(page)


main()
