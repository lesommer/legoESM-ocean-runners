#!/usr/bin/env python
"""Validate all experiment templates against the current legoESM version.

Checks that every template YAML:
1. Parses correctly
2. Has the required top-level keys
3. Maps to a valid legoESM configuration
4. Declares a recipe identity consistent with the pinned legoESM
   (ocean.recipe; see validate_recipe below)

Usage:
    python scripts/validate_templates.py
    python scripts/validate_templates.py --legoesm-dir /path/to/legoESM
    python scripts/validate_templates.py --verbose
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
VERSION_FILE = Path(__file__).resolve().parent.parent / "legoESM_version.txt"

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


def validate_template(path: Path, verbose: bool = False,
                      recipe_sources: dict | None = None) -> list[str]:
    """Validate a single template YAML. Returns list of error strings."""
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

    # Validate templates
    template_files = sorted(TEMPLATES_DIR.rglob("*.yaml"))
    print(f"\nValidating {len(template_files)} templates:\n")

    passed, failed = 0, 0
    for path in template_files:
        errors = validate_template(path, args.verbose, recipe_sources)
        rel = path.relative_to(TEMPLATES_DIR)
        if errors:
            failed += 1
            print(f"  FAIL: {rel}")
            for e in errors:
                print(f"    - {e}")
        else:
            passed += 1

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