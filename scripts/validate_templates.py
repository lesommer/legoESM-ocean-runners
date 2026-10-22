#!/usr/bin/env python
"""Validate all experiment templates against the current legoESM version.

Checks that every template YAML:
1. Parses correctly
2. Has the required top-level keys
3. Maps to a valid legoESM configuration
4. Declares a recipe identity consistent with the pinned legoESM
   (ocean.recipe; see validate_recipe below)
5. Agrees structurally with its upstream counterpart template, where one
   exists in the pinned legoESM template library
   (config/templates/ocean/<name>.yaml; see validate_consistency below)

Usage:
    python scripts/validate_templates.py
    python scripts/validate_templates.py --legoesm-dir /path/to/legoESM
    python scripts/validate_templates.py --verbose
    python scripts/validate_templates.py --lanes-warn --legoesm-dir <checkout>
        # warn-only ocean lane surface screening (weekly sync-check)
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from pathlib import Path

import yaml

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
VERSION_FILE = Path(__file__).resolve().parent.parent / "legoESM_version.txt"
ROOT_DIR = Path(__file__).resolve().parent.parent
# The consistency gate needs _MATRIX_CASES from the runners package; it
# lives in the repo root, this script in scripts/ (same insert as
# scripts/reproduce.py).
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

REQUIRED_KEYS = {
    "experiment": ["name", "mode", "description"],
    "grid": ["type"],
    "time": [],  # validated separately: must have duration_days or duration_hours
}

VALID_MODES = {
    "ocean_scm",
    "barotropic_ocean",
    "3d_ocean",
    "3d_ocean_realistic",
    "coupled",
}

VALID_GRID_TYPES = {
    "latlon",
    "cubed_sphere",
    "gaussian",
    "mpas",
    "scm",
    "tripole",
}

# The tripole OMIP lane always assembles this catalog recipe:
# run_omip_core2.py build_tripole -> run_omip._create_setup("tripole") ->
# nemo_match_tripole_model_config (locked upstream against drift by
# tests/ocean/unit/test_recipes.py). Template knobs (KPP, bottom drag,
# SSS restoring, TKE, ...) reach the lane as physics/recipe-field
# overrides; the dycore identity is fixed.
TRIPOLE_OMIP_LANE_RECIPE = "omip_nemo_match_tripole_v1"

# Runners-owned templates that have a counterpart in the pinned legoESM
# template library (config/templates/ocean/<stem>.yaml — upstream's own
# `setup:`-pointer dialect for the same matrix cases). The consistency gate
# (issue #8, Phase 3B-1) checks each pair for structural drift at
# validation time, so an upstream rename/re-gridding surfaces at pin-bump
# time instead of run time. Graduated templates (removed here, resolved
# from the upstream library by runners/run_experiment.load_template) drop
# out of this map — drift becomes impossible once the upstream file is the
# single source of truth.
UPSTREAM_COUNTERPARTS = {
    "2d/inertia_gravity_wave": "ocean/inertia_gravity_wave",
    "global_ocean/bench": "ocean/bench",
}

# Grids the runners lane accepts for counterpart cases that are NOT in the
# matrix dispatch table (_MATRIX_CASES in runners/run_experiment.py):
#   bench — _run_bench dispatches the latlon and synthetic-tripole lanes
#   inertia_gravity_wave — stub lane; its template declares grid.type latlon
#   (stommel_gyre_tracer left the table 2026-10-22: wired into _MATRIX_CASES
#     and graduated — the gate now reads its grid family from _MATRIX_CASES)
COUNTERPART_FALLBACK_GRIDS = {
    "bench": {"latlon", "tripole"},
    "inertia_gravity_wave": {"latlon"},
}


def validate_recipe(config, experiment_recipes=None, dino_recipes=None,
                    tripole_lane_recipe=TRIPOLE_OMIP_LANE_RECIPE):
    """Validate a template's ocean.recipe against the pinned legoESM.

    Per-lane semantics (see AGENTS.md "Recipes"):

    * Matrix-lane cases (ocean.case tagged in the pinned legoESM
      recipe_map): ocean.recipe is REQUIRED and must equal the upstream
      tag — the upstream matrix case owns the recipe (verified upstream
      by tests/ocean/unit/test_recipe_map.py); the template only
      declares it. An upstream recipe rename/remapping therefore breaks
      validation at pin-bump time, not at run time (the nemo_v1 ->
      legoesm_nemo_like_v1 lesson).
    * DINO lane (mode 3d_ocean, case dino): ocean.recipe is optional;
      when set it names an upstream DINO recipe CARD (run_dino.py
      --recipe choices = DINO_RECIPES), not a recipe_map tag. Unset =
      upstream DINOConfig paper-faithful defaults.
    * Tripole OMIP lane (mode 3d_ocean_realistic, grid tripole):
      ocean.recipe, when declared, must be the lane's identity
      (TRIPOLE_OMIP_LANE_RECIPE). A template overriding dycore fields
      via run.extra_args (omip_faithful_card: --momentum-rk3,
      --pgf-scheme, --tracer-advection) must NOT declare a recipe — no
      catalog name covers the overridden identity, and recipe names are
      fidelity claims.
    * ocean_scm / coupled: no ocean dycore recipe applies (the column
      model / coupled presets own their configuration).
    * Untagged cases (no recipe_map entry): no recipe may be declared —
      never declare an unverified identity.

    The recipe sources are passed in (None = unavailable, e.g. under
    --skip-imports or in unit tests with planted-violation fixtures), so
    checks that need them degrade gracefully when legoESM is absent.
    """
    errors = []
    mode = config.get("experiment", {}).get("mode", "")
    ocean = config.get("ocean") or {}
    grid_type = (config.get("grid") or {}).get("type", "")
    recipe = ocean.get("recipe")
    case = ocean.get("case")

    if recipe is not None and not isinstance(recipe, str):
        return ["'ocean.recipe' must be a string (a named recipe), "
                f"got: {recipe!r}"]

    if mode in ("ocean_scm", "coupled"):
        if recipe is not None:
            errors.append(
                f"ocean.recipe={recipe!r} declared, but mode {mode!r} has "
                "no ocean dycore recipe (the column model / coupled "
                "preset owns its configuration)")
        return errors

    if mode == "3d_ocean" and case == "dino":
        if (recipe is not None and dino_recipes is not None
                and recipe not in dino_recipes):
            errors.append(
                f"ocean.recipe={recipe!r} is not a DINO recipe card "
                f"(run_dino.py --recipe choices: {sorted(dino_recipes)}). "
                "The dino lane takes DINO_RECIPES cards, not recipe_map "
                "dycore tags (unset = upstream DINOConfig paper defaults)")
        return errors

    if mode == "3d_ocean_realistic" and grid_type == "tripole":
        if (recipe is not None and tripole_lane_recipe is not None
                and recipe != tripole_lane_recipe):
            errors.append(
                f"ocean.recipe={recipe!r} declared, but the tripole OMIP "
                f"lane assembles {tripole_lane_recipe!r} "
                "(nemo_match_tripole_model_config); declare that or "
                "nothing (a card overriding dycore fields via "
                "run.extra_args has no honest catalog name)")
        return errors

    if experiment_recipes is None:
        return errors  # source unavailable: degrade gracefully

    if case in experiment_recipes:
        expected = experiment_recipes[case]
        if recipe is None:
            errors.append(
                f"ocean.case {case!r} is tagged {expected!r} in the "
                "pinned legoESM recipe_map (EXPERIMENT_RECIPES); declare "
                f"it: ocean.recipe: {expected}")
        elif recipe != expected:
            errors.append(
                f"ocean.recipe={recipe!r} does not match the pinned "
                f"recipe_map tag {expected!r} for ocean.case {case!r} "
                "(the upstream matrix case owns the recipe — the template "
                "declares it, it does not choose it)")
    elif recipe is not None:
        errors.append(
            f"ocean.recipe={recipe!r} declared, but ocean.case {case!r} "
            "has no verified tag in the pinned legoESM recipe_map "
            "(recipe names are fidelity claims — never declare an "
            "unverified identity)")
    return errors


def validate_consistency(config, counterpart_rel, legoesm_path,
                         matrix_cases=None, fallback_grids=None,
                         info=None):
    """Check a runners template against its pinned-upstream counterpart.

    Structural drift checks only (issue #8, Phase 3B-1 — maturity is
    reported, never blocking):

    a. the counterpart file exists in the pinned legoESM template library
       (a rename/removal upstream must fail validation, not the run lane);
    b. counterpart ``setup.name`` == the template's ``ocean.case`` — the
       upstream case owns the identity;
    c. counterpart ``setup.grid`` is in the grid family the runners lane
       dispatches for that case (values of ``_MATRIX_CASES[case]``, or the
       ``fallback_grids`` table for cases outside the matrix dispatch).

    ``info``: optional dict, filled with counterpart metadata
    (``maturity``) for the caller's informational reporting.
    """
    errors = []
    counterpart_path = (Path(legoesm_path) / "config" / "templates"
                        / f"{counterpart_rel}.yaml")
    if not counterpart_path.exists():
        errors.append(
            f"upstream counterpart missing: {counterpart_rel}.yaml not "
            "found in the pinned legoESM template library (renamed or "
            "removed upstream — update the pin, or the "
            "UPSTREAM_COUNTERPARTS map)")
        return errors
    with open(counterpart_path) as f:
        counterpart = yaml.safe_load(f)
    if not isinstance(counterpart, dict):
        return [f"upstream counterpart {counterpart_rel} is not a YAML "
                "mapping"]

    if info is not None:
        experiment = counterpart.get("experiment") or {}
        info["maturity"] = experiment.get("maturity", "unknown")

    setup = counterpart.get("setup") or {}
    case = (config.get("ocean") or {}).get("case")
    name = setup.get("name")
    if name != case:
        errors.append(
            f"setup drift: upstream counterpart declares "
            f"setup.name={name!r} but the template's ocean.case is "
            f"{case!r} (the upstream case owns the identity — the "
            "template must follow)")

    allowed = set((matrix_cases or {}).get(case, {}).values())
    allowed |= set((fallback_grids or {}).get(case, ()))
    if not allowed:
        errors.append(
            f"counterpart case {case!r} has no dispatchable grid family "
            "in this repo (extend _MATRIX_CASES or "
            "COUNTERPART_FALLBACK_GRIDS in scripts/validate_templates.py)")
    else:
        grid = setup.get("grid")
        if grid not in allowed:
            errors.append(
                f"grid drift: upstream counterpart declares "
                f"setup.grid={grid!r}, outside the grid family the "
                f"runners lane dispatches for {case!r} ({sorted(allowed)}) "
                "— the case would not run through this repo's lane")
    return errors


def check_counterpart_coverage(template_files, legoesm_path):
    """Repo-level counterpart curation checks (both directions must fail).

    * stale entry: a UPSTREAM_COUNTERPARTS key without a template file
      (e.g. left behind after graduation);
    * undeclared overlap (auto-discovery): a runners template whose stem
      has an upstream counterpart file in the pinned legoESM but is not
      declared in UPSTREAM_COUNTERPARTS — a new upstream overlap must be
      consciously curated (check it for drift, or graduate it), never
      silently skipped.

    Returns (errors, maturities): maturities maps each declared
    counterpart to its upstream ``experiment.maturity`` (informational).
    """
    errors = []
    rels = {}
    for path in template_files:
        rels[str(path.relative_to(TEMPLATES_DIR).with_suffix(""))] = path

    stale = sorted(k for k in UPSTREAM_COUNTERPARTS if k not in rels)
    for rel in stale:
        errors.append(
            f"UPSTREAM_COUNTERPARTS entry {rel!r} has no template file "
            "(stale entry — remove it; graduated templates drop out of "
            "the map)")

    maturities = {}
    upstream_dir = Path(legoesm_path) / "config" / "templates" / "ocean"
    upstream_stems = (
        {p.stem for p in upstream_dir.glob("*.yaml")} if upstream_dir.is_dir()
        else set()
    )
    for rel, counterpart_rel in sorted(UPSTREAM_COUNTERPARTS.items()):
        counterpart_path = (Path(legoesm_path) / "config" / "templates"
                            / f"{counterpart_rel}.yaml")
        if counterpart_path.exists():
            with open(counterpart_path) as f:
                counterpart = yaml.safe_load(f) or {}
            maturity = (counterpart.get("experiment") or {}).get(
                "maturity", "unknown")
            maturities[counterpart_rel] = maturity

    undeclared = sorted(
        rel for rel, path in rels.items()
        if path.stem in upstream_stems and rel not in UPSTREAM_COUNTERPARTS
    )
    for rel in undeclared:
        errors.append(
            f"template {rel!r} has an upstream counterpart "
            f"(ocean/{Path(rel).stem}.yaml) but is not declared in "
            "UPSTREAM_COUNTERPARTS — either declare the overlap (drift "
            "gate) or graduate the template (runners/run_experiment.py "
            "alias map)")
    return errors, maturities


# ---------------------------------------------------------------------------
# Ocean lane screening gate (issue #10)
# ---------------------------------------------------------------------------
#
# The Phase-3B gates watch runners TEMPLATES (registry parity,
# auto-discovery, counterpart drift) — they cannot see a NEW UPSTREAM LANE
# (a matrix case, a recipe-catalog entry, an ocean driver script, a
# non-`ocean/` upstream template). check_ocean_lane_coverage() closes that
# gap: it enumerates the pinned legoESM ocean surface IMPORT-FREE (AST
# parse + the _load_pinned_experiment_recipes file-path trick — no legoesm
# package import needed) and fails validation on any enumerated lane
# without a disposition in docs/ocean_lane_dispositions.yaml, and on any
# disposition entry that no longer matches an enumerated lane (stale).
# Blocking where validation already runs with the checkout present: pin
# bumps (sync_legoesm.sh validates BEFORE the atomic pin write) + CI
# Tier-2. The weekly sync-check runs the same enumeration at upstream main
# in warn-only mode (--lanes-warn).

DISPOSITIONS_FILE = ROOT_DIR / "docs" / "ocean_lane_dispositions.yaml"

LANE_NAMESPACES = ("matrix", "recipe", "experiment_recipe", "script", "template")

LANE_STATUSES = {
    "onboarded",      # runners run lane exists (matrix dispatch), receipt recorded
    "graduated",      # onboarded + template resolved from the pinned upstream library
    "upstream_only",  # init via ocean/<stem> works; receipts are upstream's business
    "delegation",     # served by a dedicated delegation lane (dino, bench)
    "declined",       # out of scope / variant / defect — reason REQUIRED
    "backlog",        # pending onboarding (issue #10 tiers)
}

_REASONS_REQUIRED = {"declined"}

# The pinned matrix runner: its RUNNERS dispatch dict + TestCase appends
# are the matrix-lane surface. AST-parsed, never imported (the module
# pulls in jax).
_MATRIX_SCRIPT_REL = "scripts/matrix/run_ocean_test_matrix.py"

# Module-level string-list constants the TestCase-append loops iterate
# over — the only module constants the symbolic evaluator needs.
_MATRIX_GRID_CONSTS = ("GRID_TYPES", "_OPTIONAL_GRIDS")

# Scripts outside scripts/run/ that are lane surface by the issue-#10
# scope decision (SW/Williamson included): the Williamson delegation
# target and the SW convergence deck (imports legoesm.grids, not
# legoesm.ocean — the import scan cannot see them).
_SCRIPT_SURFACE_EXTRA = (
    "scripts/matrix/run_atmosphere_test_matrix.py",
    "scripts/run/run_w2_mpas_convergence.py",
)

# Recipe catalogs, loaded by file path (import-standalone at the pin —
# the same trick as runners.run_experiment._load_pinned_experiment_recipes;
# no legoesm package install needed).
_RECIPE_CATALOGS = (
    ("packages/ocean/legoesm/ocean/recipes.py",
     ("LATLON_RECIPES", "MPAS_RECIPES")),
    ("packages/ocean/legoesm/ocean/experiments/recipe_map.py",
     ("EXPERIMENT_RECIPES",)),
)

# Import prefixes that make a scripts/run/*.py ocean-relevant lane surface.
_OCEAN_IMPORT_PREFIXES = ("legoesm.ocean", "fesom_jax")


class _SurfaceEnumerationError(RuntimeError):
    """The pinned surface could not be enumerated — the gate fails closed."""


def _top_level_assign(tree, name):
    """The value node of a module-level assignment to `name`, or None."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            if isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
                return node.value
        elif (isinstance(node, ast.AnnAssign) and node.value is not None
                and isinstance(node.target, ast.Name) and node.target.id == name):
            return node.value
    return None


def _eval_string_list(node, consts, env=None):
    """Statically evaluate an expression denoting string(s) (fail-closed).

    Supports exactly the idioms the pinned matrix builder uses: string
    constants, list/tuple literals, module-level string-list constants,
    loop variables (via ``env``), ``+`` concatenation, and conditional
    expressions — where both branches are UNIONED so the enumerated surface
    is availability-independent (e.g. ``["fesom"] if _fesom_available()
    else []`` contributes ``fesom``). Anything else is an error.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        if env is not None and node.id in env:
            return [env[node.id]]
        if node.id in consts:
            return _eval_string_list(consts[node.id], consts, env)
        raise _SurfaceEnumerationError(
            f"matrix surface: unknown name {node.id!r} — extend the "
            "enumerator's symbolic evaluator")
    if isinstance(node, (ast.List, ast.Tuple)):
        out = []
        for elt in node.elts:
            out.extend(_eval_string_list(elt, consts, env))
        return out
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (_eval_string_list(node.left, consts, env)
                + _eval_string_list(node.right, consts, env))
    if isinstance(node, ast.IfExp):
        return (_eval_string_list(node.body, consts, env)
                + _eval_string_list(node.orelse, consts, env))
    raise _SurfaceEnumerationError(
        "matrix surface: unsupported expression at line "
        f"{getattr(node, 'lineno', '?')}: {ast.unparse(node)[:120]} — "
        "extend the enumerator's symbolic evaluator")


def _one_string(node, consts, env, what):
    values = _eval_string_list(node, consts, env)
    if len(values) != 1:
        raise _SurfaceEnumerationError(
            f"matrix surface: TestCase {what} is not a single string")
    return values[0]


def _continue_exclusions(body, varname):
    """Constants excluded from a loop via ``if <var> == "<x>": continue``."""
    excluded = set()
    for stmt in body:
        if (isinstance(stmt, ast.If)
                and isinstance(stmt.test, ast.Compare)
                and isinstance(stmt.test.left, ast.Name)
                and stmt.test.left.id == varname
                and len(stmt.test.ops) == 1
                and isinstance(stmt.test.ops[0], ast.Eq)
                and len(stmt.test.comparators) == 1
                and isinstance(stmt.test.comparators[0], ast.Constant)
                and isinstance(stmt.test.comparators[0].value, str)
                and any(isinstance(n, ast.Continue) for n in stmt.body)):
            excluded.add(stmt.test.comparators[0].value)
    return excluded


def _collect_testcase_arms(stmts, consts, arms, env=None):
    """Collect (case, grid) arms from TestCase(...) appends (fail-closed)."""
    env = dict(env or {})
    for stmt in stmts:
        if isinstance(stmt, ast.For):
            if not isinstance(stmt.target, ast.Name):
                raise _SurfaceEnumerationError(
                    "matrix surface: non-Name loop target — extend the enumerator")
            values = _eval_string_list(stmt.iter, consts, env)
            excluded = _continue_exclusions(stmt.body, stmt.target.id)
            for value in values:
                if value in excluded:
                    continue
                inner = dict(env)
                inner[stmt.target.id] = value
                _collect_testcase_arms(stmt.body, consts, arms, inner)
            if stmt.orelse:
                _collect_testcase_arms(stmt.orelse, consts, arms, env)
        elif isinstance(stmt, ast.If):
            # Conservative: walk both branches (no static conditionals in
            # the matrix builder at the pin).
            _collect_testcase_arms(stmt.body, consts, arms, env)
            _collect_testcase_arms(stmt.orelse, consts, arms, env)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            raise _SurfaceEnumerationError(
                "matrix surface: nested def/class inside _build_test_matrix "
                "— extend the enumerator")
        else:
            for node in ast.walk(stmt):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "TestCase" and node.args):
                    case = _one_string(node.args[0], consts, env, "case")
                    grid = _one_string(node.args[1], consts, env, "grid")
                    arms.setdefault(case, set()).add(grid)


def _enumerate_matrix_cases(legoesm_path):
    """RUNNERS dispatch cases -> sorted TestCase grid sets (AST, no import)."""
    path = Path(legoesm_path) / _MATRIX_SCRIPT_REL
    if not path.exists():
        raise _SurfaceEnumerationError(
            f"matrix surface: {_MATRIX_SCRIPT_REL} not found at {legoesm_path}")
    tree = ast.parse(path.read_text())
    consts = {}
    for name in _MATRIX_GRID_CONSTS:
        node = _top_level_assign(tree, name)
        if node is None:
            raise _SurfaceEnumerationError(
                f"matrix surface: {_MATRIX_SCRIPT_REL} no longer defines "
                f"{name} at module level — extend the enumerator")
        consts[name] = node
    runners_node = _top_level_assign(tree, "RUNNERS")
    if not isinstance(runners_node, ast.Dict) or not runners_node.keys or not all(
            isinstance(k, ast.Constant) and isinstance(k.value, str)
            for k in runners_node.keys):
        raise _SurfaceEnumerationError(
            "matrix surface: RUNNERS is not a literal str-keyed dict — "
            "extend the enumerator")
    runners = [k.value for k in runners_node.keys]
    build = next((n for n in tree.body
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_build_test_matrix"), None)
    if build is None:
        raise _SurfaceEnumerationError(
            "matrix surface: _build_test_matrix not found — extend the enumerator")
    arms: dict[str, set] = {}
    _collect_testcase_arms(build.body, consts, arms)
    undisp = sorted(set(arms) - set(runners))
    if undisp:
        raise _SurfaceEnumerationError(
            "matrix surface: TestCase cases without a RUNNERS dispatch "
            f"entry: {undisp} — the dispatch may have moved; extend the "
            "enumerator")
    return {case: sorted(arms.get(case, ())) for case in sorted(runners)}


def _enumerate_recipe_keys(legoesm_path):
    """Recipe-catalog keys, loaded by file path (import-standalone modules)."""
    out = {"recipe": [], "experiment_recipe": []}
    for rel, attrs in _RECIPE_CATALOGS:
        path = Path(legoesm_path) / rel
        if not path.exists():
            raise _SurfaceEnumerationError(
                f"recipe surface: {rel} not found at {legoesm_path}")
        spec = importlib.util.spec_from_file_location(
            f"_runners_lane_surface_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise _SurfaceEnumerationError(
                f"recipe surface: {rel} is no longer import-standalone "
                f"({exc}) — extend the lane enumerator")
        for attr in attrs:
            catalog = getattr(module, attr, None)
            if not isinstance(catalog, dict) or not all(
                    isinstance(k, str) for k in catalog):
                raise _SurfaceEnumerationError(
                    f"recipe surface: {rel}:{attr} is not a str-keyed dict")
            ns = ("experiment_recipe" if attr == "EXPERIMENT_RECIPES"
                  else "recipe")
            out[ns].extend(catalog)
    return {"recipe": sorted(set(out["recipe"])),
            "experiment_recipe": sorted(set(out["experiment_recipe"]))}


def _enumerate_ocean_scripts(legoesm_path):
    """Ocean-relevant scripts/run/**.py (AST import scan) + SW inclusions."""
    root = Path(legoesm_path) / "scripts" / "run"
    if not root.is_dir():
        raise _SurfaceEnumerationError(
            f"script surface: {root} not found at {legoesm_path}")
    found = []
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError as exc:
            raise _SurfaceEnumerationError(
                f"script surface: {path} does not parse ({exc})")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            else:
                continue
            if any(m.startswith(_OCEAN_IMPORT_PREFIXES) for m in mods):
                found.append(str(path.relative_to(legoesm_path)))
                break
    for rel in _SCRIPT_SURFACE_EXTRA:
        if not (Path(legoesm_path) / rel).exists():
            raise _SurfaceEnumerationError(
                f"script surface: explicit inclusion {rel} not found at "
                f"{legoesm_path} (upstream moved it — update "
                "_SCRIPT_SURFACE_EXTRA)")
        found.append(rel)
    return sorted(set(found))


def _enumerate_upstream_templates(legoesm_path):
    """Upstream template stems (<category>/<stem>), ALL categories."""
    tdir = Path(legoesm_path) / "config" / "templates"
    if not tdir.is_dir():
        raise _SurfaceEnumerationError(
            f"template surface: {tdir} not found at {legoesm_path}")
    return sorted(str(p.relative_to(tdir).with_suffix(""))
                  for p in tdir.rglob("*.yaml"))


def enumerate_ocean_surface(legoesm_path):
    """Enumerate the pinned legoESM ocean lane surface (import-free).

    Returns {"matrix": {case: [grids...]}, "recipe": [...],
             "experiment_recipe": [...], "script": [...],
             "template": [...]}. Raises _SurfaceEnumerationError when any
    surface cannot be parsed — the gate fails closed, never silently skips.
    """
    legoesm_path = Path(legoesm_path)
    surface = {"matrix": _enumerate_matrix_cases(legoesm_path)}
    surface.update(_enumerate_recipe_keys(legoesm_path))
    surface["script"] = _enumerate_ocean_scripts(legoesm_path)
    surface["template"] = _enumerate_upstream_templates(legoesm_path)
    return surface


def load_lane_dispositions(path=None):
    """Load + schema-check the lane disposition table."""
    path = Path(path) if path is not None else DISPOSITIONS_FILE
    if not path.exists():
        raise _SurfaceEnumerationError(f"lane dispositions not found: {path}")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("lanes"), dict):
        raise _SurfaceEnumerationError(
            f"{path}: expected a top-level 'lanes' mapping")
    for key, entry in data["lanes"].items():
        ns, sep, ident = str(key).partition(":")
        if (not sep or ns not in LANE_NAMESPACES or not ident):
            raise _SurfaceEnumerationError(
                f"{path}: {key!r} is not <namespace>:<id> "
                f"(namespaces: {', '.join(LANE_NAMESPACES)})")
        if not isinstance(entry, dict):
            raise _SurfaceEnumerationError(
                f"{path}: {key!r} entry must be a mapping")
        status = entry.get("status")
        if status not in LANE_STATUSES:
            raise _SurfaceEnumerationError(
                f"{path}: {key!r} status {status!r} not in "
                f"{sorted(LANE_STATUSES)}")
        if status in _REASONS_REQUIRED and not str(entry.get("reason", "")).strip():
            raise _SurfaceEnumerationError(
                f"{path}: {key!r} status 'declined' requires a reason")
        if ns == "matrix":
            grids = entry.get("grids")
            if not isinstance(grids, list) or not all(
                    isinstance(g, str) for g in grids):
                raise _SurfaceEnumerationError(
                    f"{path}: {key!r} matrix entries must record 'grids' "
                    "(the pinned TestCase grid set)")
    return data["lanes"]


def _match_disposition(lanes, ns, ident):
    """Find the disposition for a lane: exact key, or longest script/
    template prefix entry (ids ending in '/'). Returns (key, entry)."""
    exact = lanes.get(f"{ns}:{ident}")
    if exact is not None:
        return f"{ns}:{ident}", exact
    if ns in ("script", "template"):
        best = None
        for key, entry in lanes.items():
            k_ns, sep, k_id = str(key).partition(":")
            if k_ns != ns or not sep or not k_id.endswith("/"):
                continue
            if ident.startswith(k_id) and (
                    best is None
                    or len(k_id) > len(best[0].partition(":")[2])):
                best = (key, entry)
        if best is not None:
            return best
    return None, None


def _lane_coverage_diffs(surface, lanes):
    """Diff the enumerated surface against the dispositions.

    Returns (missing, drifted, stale): un-dispositioned lanes; matrix
    entries whose recorded grid set drifted from the pinned TestCase grid
    set; disposition entries matching no enumerated lane.
    """
    missing, drifted = [], []
    matched = set()
    matrix_grids = surface["matrix"]
    for ns in LANE_NAMESPACES:
        idents = (sorted(matrix_grids) if ns == "matrix" else surface[ns])
        for ident in idents:
            key, entry = _match_disposition(lanes, ns, ident)
            if key is None:
                missing.append(f"{ns}:{ident}")
                continue
            matched.add(key)
            if ns == "matrix":
                recorded = sorted((entry or {}).get("grids", []))
                if recorded != sorted(matrix_grids[ident]):
                    drifted.append(f"{ns}:{ident}")
    stale = sorted(k for k in lanes if k not in matched)
    return missing, drifted, stale


def check_ocean_lane_coverage(legoesm_path, dispositions_path=None,
                              verbose=False):
    """Lane screening gate: every enumerated lane needs a disposition.

    Fails on: an enumerated lane with no disposition entry (exact, or a
    prefix entry for script/template lanes); a disposition entry matching
    no enumerated lane (stale); a matrix entry whose recorded grid set
    drifted from the pinned TestCase grid set; schema violations (unknown
    status, declined without reason, matrix entry without grids).

    Returns (errors, counts); counts maps namespace -> enumerated size.
    """
    surface = enumerate_ocean_surface(legoesm_path)
    lanes = load_lane_dispositions(dispositions_path)
    missing, drifted, stale = _lane_coverage_diffs(surface, lanes)
    errors = []
    for ident in missing:
        errors.append(
            f"un-dispositioned ocean lane: {ident} exists in the pinned "
            "legoESM but has no entry in "
            f"{DISPOSITIONS_FILE.relative_to(ROOT_DIR)} — add a "
            "disposition (every new upstream lane must be consciously "
            "curated, never silently skipped)")
    for ident in drifted:
        entry = lanes.get(ident) or {}
        errors.append(
            f"grid drift for {ident}: recorded "
            f"{sorted((entry or {}).get('grids', []))} != pinned TestCase "
            f"grid set {sorted(surface['matrix'][ident.split(':', 1)[1]])} "
            "— update the disposition (or the lane wiring) consciously")
    for key in stale:
        errors.append(
            f"stale lane disposition: {key} matches no lane in the pinned "
            "legoESM surface — remove it or fix the id")
    counts = {ns: (len(surface["matrix"]) if ns == "matrix"
                   else len(surface[ns])) for ns in LANE_NAMESPACES}
    if verbose:
        total = sum(counts.values())
        breakdown = ", ".join(f"{ns}={counts[ns]}" for ns in LANE_NAMESPACES)
        print(f"  lane surface: {total} lanes ({breakdown}); "
              f"{len(lanes)} dispositions")
    return errors, counts


def _run_lanes_warn(legoesm_path):
    """--lanes-warn: warn-only screening of a checkout's ocean surface.

    Informational companion of check_ocean_lane_coverage for the weekly
    sync-check: enumerates the surface at the given checkout (typically
    upstream main) and emits GitHub ::warning:: annotations for lanes that
    will need a disposition at the next pin bump (missing entries + grid
    drift). Stale entries do NOT warn — patch-side additions legitimately
    differ between the pinned tree and upstream main. Drift exits 0; an
    enumeration/schema failure prints ::error:: and exits 1 (fail-closed).
    """
    try:
        surface = enumerate_ocean_surface(legoesm_path)
        lanes = load_lane_dispositions()
    except _SurfaceEnumerationError as exc:
        print(f"::error::{exc}")
        return 1
    missing, drifted, _stale = _lane_coverage_diffs(surface, lanes)
    if not missing and not drifted:
        print("lane surface matches dispositions (warn-only: nothing pending)")
        return 0
    for ident in missing:
        print(f"::warning::un-dispositioned ocean lane at upstream: {ident} "
              "— add a disposition in docs/ocean_lane_dispositions.yaml "
              "before the next pin bump")
    for ident in drifted:
        print(f"::warning::grid drift at upstream: {ident} — update the "
              "disposition's recorded grid set before the next pin bump")
    print(f"lane surface warnings: {len(missing)} missing, "
          f"{len(drifted)} drifted")
    return 0


def validate_template(path: Path, verbose: bool = False,
                      recipe_sources: dict | None = None,
                      consistency_sources: dict | None = None) -> list[str]:
    """Validate a single template YAML. Returns list of error strings.

    ``consistency_sources`` (issue #8, Phase 3B-1): when given, templates
    declared in UPSTREAM_COUNTERPARTS are also checked against their
    pinned-upstream counterpart (see validate_consistency). None =
    unavailable/degraded (e.g. --skip-imports, out-of-repo paths).
    """
    errors = []

    try:
        with open(path) as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return [f"YAML parse error: {e}"]

    if not isinstance(config, dict):
        return ["Template is not a YAML mapping"]

    for section, keys in REQUIRED_KEYS.items():
        section_data = config.get(section)
        if section_data is None:
            errors.append(f"Missing section: '{section}'")
            continue
        for key in keys:
            if key not in section_data:
                errors.append(f"Missing key: '{section}.{key}'")

    mode = config.get("experiment", {}).get("mode", "")
    if mode and mode not in VALID_MODES:
        errors.append(
            f"Invalid mode: '{mode}'. Valid: {sorted(VALID_MODES)}"
        )

    grid_type = config.get("grid", {}).get("type", "")
    if grid_type and grid_type not in VALID_GRID_TYPES:
        errors.append(
            f"Invalid grid_type: '{grid_type}'. Valid: {sorted(VALID_GRID_TYPES)}"
        )

    # Validate time section: must have duration_days or duration_hours
    time_cfg = config.get("time", {})
    if time_cfg and "duration_days" not in time_cfg and "duration_hours" not in time_cfg:
        errors.append("Missing key: 'time.duration_days' or 'time.duration_hours'")

    # Validate requires_patches: optional list of patch filenames
    requires_patches = config.get("requires_patches")
    if requires_patches is not None:
        if not isinstance(requires_patches, list):
            errors.append("'requires_patches' must be a list")
        else:
            import re
            for entry in requires_patches:
                if not isinstance(entry, str):
                    errors.append(f"'requires_patches' entry must be a string, got: {entry!r}")
                elif not re.match(r"^\d{3}-", entry):
                    errors.append(
                        f"'requires_patches' entry must match NNN-description.patch format, got: '{entry}'"
                    )

    # Validate ocean.recipe against the pinned legoESM catalogs
    errors.extend(validate_recipe(config, **(recipe_sources or {})))

    # Upstream-counterpart consistency gate (Phase 3B-1): structural
    # agreement with the pinned legoESM template library, where declared.
    if consistency_sources is not None:
        try:
            rel = str(path.relative_to(TEMPLATES_DIR).with_suffix(""))
        except ValueError:
            rel = None  # out-of-repo path (unit-test fixture): no gate
        counterpart_rel = UPSTREAM_COUNTERPARTS.get(rel) if rel else None
        if counterpart_rel:
            info: dict = {}
            errors.extend(validate_consistency(
                config, counterpart_rel,
                consistency_sources["legoesm_path"],
                consistency_sources.get("matrix_cases"),
                consistency_sources.get("fallback_grids"),
                info=info))
            if verbose:
                print(f"    counterpart={counterpart_rel} "
                      f"(maturity: {info.get('maturity', 'unknown')})")

    if verbose:
        name = config.get("experiment", {}).get("name", "?")
        mode = config.get("experiment", {}).get("mode", "?")
        grid = config.get("grid", {}).get("type", "?")
        res = config.get("grid", {}).get("resolution", "?")
        nlev = config.get("grid", {}).get("n_levels", config.get("grid", {}).get("nlev", "?"))
        rp = config.get("requires_patches", [])
        recipe = (config.get("ocean") or {}).get("recipe")
        extra = f", requires_patches={rp}" if rp else ""
        recipe_extra = f", recipe={recipe}" if recipe else ""
        print(f"  {path.relative_to(TEMPLATES_DIR)}: name={name}, mode={mode}, "
              f"grid={grid}/{res}/{nlev}lev{recipe_extra}{extra}")

    return errors


def validate_legoesm_import(legoesm_path: Path, verbose: bool = False) -> list[str]:
    """Check that legoESM can be imported and key modules exist."""
    errors = []
    import importlib

    try:
        import legoesm
        if verbose:
            print(f"  legoesm imported from: {legoesm_path}")
    except ImportError as e:
        errors.append(f"Cannot import legoesm: {e}")
        return errors

    for module in [
        "legoesm.driver.config",
        "legoesm.driver.model_driver",
        "legoesm.ocean.state",
        "legoesm.ocean.physics",
    ]:
        try:
            importlib.import_module(module)
            if verbose:
                print(f"  {module}: OK")
        except ImportError as e:
            errors.append(f"Cannot import {module}: {e}")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate legoESM experiment templates")
    parser.add_argument("--legoesm-dir", type=Path, default=None,
                        help="Path to legoESM checkout")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show detailed output")
    parser.add_argument("--skip-imports", action="store_true",
                        help="Skip legoESM import validation")
    parser.add_argument("--lanes-warn", action="store_true",
                        help="Warn-only screening of the ocean lane surface "
                             "at the given checkout (the weekly sync-check "
                             "runs this against upstream main; import-free, "
                             "non-blocking, exits 0 on drift)")

    args = parser.parse_args()

    if args.legoesm_dir is None:
        legoesm_path = Path(__file__).resolve().parent.parent.parent / "legoESM"
    else:
        legoesm_path = args.legoesm_dir

    # Read pinned version
    version_info = {}
    for line in VERSION_FILE.read_text().strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            version_info[key.strip()] = val.strip()

    print(f"legoESM pinned version: {version_info.get('commit', 'unknown')} "
          f"(ref: {version_info.get('ref', 'unknown')})")

    # Warn-only lane screening short-circuits everything else (the weekly
    # sync-check runs it against a checkout of upstream main; import-free).
    if args.lanes_warn:
        sys.exit(_run_lanes_warn(legoesm_path))

    # Recipe catalogs from the pinned legoESM: matrix-lane recipe tags
    # (recipe_map.EXPERIMENT_RECIPES) + DINO recipe cards (DINO_RECIPES).
    # With imports enabled, unavailable catalogs are a FAILURE (not a
    # silent skip): the ocean.recipe gate must be able to fail. Use
    # --skip-imports for structural-only checks.
    recipe_sources = None
    recipe_import_error = None
    if not args.skip_imports:
        try:
            from legoesm.ocean.experiments.recipe_map import EXPERIMENT_RECIPES
            from legoesm.ocean.experiments.dino import DINO_RECIPES
            recipe_sources = {
                "experiment_recipes": dict(EXPERIMENT_RECIPES),
                "dino_recipes": set(DINO_RECIPES),
            }
            print(f"Recipe catalogs: {len(recipe_sources['experiment_recipes'])} "
                  f"recipe_map tags, {len(recipe_sources['dino_recipes'])} DINO cards")
        except ImportError as e:
            recipe_import_error = (
                f"Cannot load legoESM recipe catalogs ({e}) — ocean.recipe "
                "validation needs the pinned legoESM installed (uv sync / "
                "scripts/experiment/install_federation.py --all); use "
                "--skip-imports for structural-only checks")

    # Consistency-gate sources (Phase 3B-1): the matrix dispatch table is
    # the runners' grid-family source of truth; the pinned legoESM
    # checkout supplies the counterpart templates. Like recipe_sources,
    # None = degraded (--skip-imports).
    consistency_sources = None
    if not args.skip_imports:
        from runners.run_experiment import _MATRIX_CASES
        consistency_sources = {
            "legoesm_path": legoesm_path,
            "matrix_cases": _MATRIX_CASES,
            "fallback_grids": COUNTERPART_FALLBACK_GRIDS,
        }
    else:
        print("Consistency gate: skipped (--skip-imports; upstream "
              "counterparts not checked)")
        print("Lane coverage gate: skipped (--skip-imports; the pinned "
              "checkout is required for the lane surface enumeration)")

    # Validate templates
    template_files = sorted(TEMPLATES_DIR.rglob("*.yaml"))
    print(f"\nValidating {len(template_files)} templates:\n")

    passed, failed = 0, 0
    for path in template_files:
        errors = validate_template(path, args.verbose, recipe_sources,
                                   consistency_sources)
        rel = path.relative_to(TEMPLATES_DIR)
        if errors:
            failed += 1
            print(f"  FAIL: {rel}")
            for e in errors:
                print(f"    - {e}")
        else:
            passed += 1

    # Counterpart coverage (repo-level gate directions): stale entries and
    # undeclared upstream overlaps. Maturities are informational only.
    if consistency_sources is not None:
        coverage_errors, maturities = check_counterpart_coverage(
            template_files, legoesm_path)
        if coverage_errors:
            print("\nCounterpart coverage:")
            for e in coverage_errors:
                print(f"  - {e}")
            failed += 1
        maturity_counts: dict[str, int] = {}
        for m in maturities.values():
            maturity_counts[m] = maturity_counts.get(m, 0) + 1
        summary = ", ".join(f"{n} {m}" for m, n in sorted(maturity_counts.items()))
        print(f"\nConsistency gate: {len(UPSTREAM_COUNTERPARTS)} declared "
              f"counterparts checked (upstream maturities — {summary})")

    # Lane screening gate (issue #10): every ocean-relevant lane in the
    # pinned legoESM needs a disposition. Import-gated: the enumeration
    # reads the pinned checkout (import-free), so --skip-imports (no
    # checkout: CI Tier-1) skips it. Blocking where validation already
    # runs with the checkout present: pin bumps (sync_legoesm.sh validates
    # before the atomic pin write) + CI Tier-2.
    if not args.skip_imports:
        print("\nOcean lane coverage (screening gate, issue #10):")
        try:
            lane_errors, _lane_counts = check_ocean_lane_coverage(
                legoesm_path, verbose=args.verbose)
        except _SurfaceEnumerationError as exc:
            print(f"  FAIL: {exc}")
            failed += 1
        else:
            if lane_errors:
                for err in lane_errors:
                    print(f"  - {err}")
                failed += 1
            else:
                print("  all enumerated lanes carry dispositions")

    # Validate legoESM imports
    if not args.skip_imports:
        print(f"\nValidating legoESM imports from: {legoesm_path}")
        if recipe_import_error is not None:
            print(f"  IMPORT ERROR: {recipe_import_error}")
            failed += 1
        if legoesm_path.exists():
            import_errors = validate_legoesm_import(legoesm_path, args.verbose)
            if import_errors:
                for e in import_errors:
                    print(f"  IMPORT ERROR: {e}")
                failed += 1
        else:
            print(f"  WARNING: legoESM not found at {legoesm_path}")
            print(f"           Set --legoesm-dir or LEGOESM_DIR environment variable")

    print(f"\n{'='*60}")
    print(f"Templates: {passed} passed, {failed} failed, {len(template_files)} total")

    if failed > 0:
        sys.exit(1)
    print("All templates valid.")


if __name__ == "__main__":
    main()