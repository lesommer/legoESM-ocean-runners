#!/usr/bin/env python
"""Validate all experiment templates against the current legoESM version.

Checks that every template YAML:
1. Parses correctly
2. Has the required top-level keys
3. Maps to a valid legoESM configuration

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
    "atmosphere_only",
    "atmosphere_only_aimip",
    "coupled",
}

VALID_GRID_TYPES = {
    "latlon",
    "cubed_sphere",
    "gaussian",
    "mpas",
    "scm",
}


def validate_template(path: Path, verbose: bool = False) -> list[str]:
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

    if verbose:
        name = config.get("experiment", {}).get("name", "?")
        mode = config.get("experiment", {}).get("mode", "?")
        grid = config.get("grid", {}).get("type", "?")
        res = config.get("grid", {}).get("resolution", "?")
        nlev = config.get("grid", {}).get("n_levels", config.get("grid", {}).get("nlev", "?"))
        print(f"  {path.relative_to(TEMPLATES_DIR)}: name={name}, mode={mode}, "
              f"grid={grid}/{res}/{nlev}lev")

    return errors


def validate_legoesm_import(legoesm_path: Path, verbose: bool = False) -> list[str]:
    """Check that legoESM can be imported and key modules exist."""
    errors = []
    import importlib

    sys.path.insert(0, str(legoesm_path / "src"))

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

    # Validate templates
    template_files = sorted(TEMPLATES_DIR.rglob("*.yaml"))
    print(f"\nValidating {len(template_files)} templates:\n")

    passed, failed = 0, 0
    for path in template_files:
        errors = validate_template(path, args.verbose)
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