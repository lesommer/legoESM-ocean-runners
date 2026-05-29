"""Generic experiment runner.

Loads a template YAML, applies overrides, resolves the legoESM version,
builds the appropriate config, runs the experiment, and writes a tag file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
PATCHES_DIR = Path(__file__).resolve().parent.parent / "patches"
VERSION_FILE = Path(__file__).resolve().parent.parent / "legoESM_version.txt"
EXPERIMENTS_DIR = Path(__file__).resolve().parent.parent / "experiments"


def load_version_info() -> dict[str, str]:
    """Read legoESM_version.txt and return parsed fields."""
    info: dict[str, str] = {}
    for line in VERSION_FILE.read_text().strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            info[key.strip()] = val.strip()
    return info


def resolve_legoesm_path() -> Path:
    """Find the legoESM checkout to use.

    Search order:
    1. LEGOESM_DIR environment variable
    2. ../legoESM (sibling of this repo)
    3. Installed package location
    """
    env_dir = os.environ.get("LEGOESM_DIR")
    if env_dir:
        return Path(env_dir)
    sibling = Path(__file__).resolve().parent.parent.parent / "legoESM"
    if sibling.is_dir():
        return sibling
    try:
        import legoesm
        return Path(legoesm.__file__).resolve().parent.parent
    except ImportError:
        print("ERROR: Cannot find legoESM. Set LEGOESM_DIR or install legoesm.", file=sys.stderr)
        sys.exit(1)


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_template(template_name: str) -> dict:
    """Load a template YAML by name (e.g. '3d_idealized/baroclinic_gyre')."""
    path = TEMPLATES_DIR / f"{template_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def apply_overrides(config: dict, overrides: list[str]) -> dict:
    """Apply CLI override strings like 'ocean.A_h=1e5' to a config dict.

    Dot-notation keys set nested values. Values are parsed as Python literals;
    if parsing fails they are kept as strings.
    """
    import ast
    for override in overrides:
        key, _, value_str = override.partition("=")
        keys = key.split(".")
        try:
            value = ast.literal_eval(value_str)
        except (ValueError, SyntaxError):
            value = value_str
        d = config
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value
    return config


def detect_mode(config: dict) -> str:
    """Determine the run mode from the experiment config."""
    return config.get("experiment", {}).get("mode", "unknown")


def build_atmosphere_config(config: dict, legoesm_path: Path):
    """Build an ExperimentConfig from an atmosphere-mode template."""
    sys.path.insert(0, str(legoesm_path / "src"))
    from legoesm.driver.config import (
        DycoreConfig,
        ExperimentConfig,
        GridConfig,
        OutputConfig,
    )

    grid_cfg = config.get("grid", {})
    atm_cfg = config.get("atmosphere", {})
    time_cfg = config.get("time", {})
    out_cfg = config.get("output", {})
    hw_cfg = config.get("hardware", {})

    exp = ExperimentConfig(
        grid=GridConfig(
            grid_type=grid_cfg.get("type", "cubed_sphere"),
            resolution=grid_cfg.get("resolution", 48),
            nlev=grid_cfg.get("n_levels", grid_cfg.get("nlev", 40)),
            vertical_coord=grid_cfg.get("vertical_coord", "hybrid"),
            p_top_Pa=grid_cfg.get("p_top_Pa", 200.0),
        ),
        dycore=DycoreConfig(
            model_type=atm_cfg.get("dynamics", atm_cfg.get("equations", "hydrostatic")),
            discretization=atm_cfg.get("discretization", "cdgrid"),
            dt=atm_cfg.get("dt_seconds", 600.0),
        ),
        output=OutputConfig(
            output_dir=out_cfg.get("path", ""),
            diag_days=out_cfg.get("diag_days", 5),
        ),
        days=int(time_cfg.get("duration_days", time_cfg.get("duration_hours", 120 * 24) / 24)),
        radiation=grid_cfg.get("radiation", config.get("radiation", "gray")),
        convection=config.get("convection", "sbm"),
        turbulence=config.get("turbulence", "none"),
        cloud_scheme=config.get("clouds", "none"),
        microphysics=config.get("microphysics", "none"),
    )
    return exp


def build_ocean_config(config: dict, legoesm_path: Path):
    """Build an ocean config from a 3d_ocean / barotropic_ocean / ocean_scm template.

    Returns (model, grid, coord, ocean_config, initial_conditions) ready to run.
    """
    sys.path.insert(0, str(legoesm_path / "src"))

    from legoesm.ocean.state import LatLonCGridOceanConfig
    from legoesm.ocean.physics import (
        OceanPhysicsConfig,
        VerticalMixingConfig,
        SurfaceForcingConfig,
        BottomDragConfig,
        ShortwavePenetrationConfig,
    )

    grid_cfg = config.get("grid", {})
    ocean_cfg = config.get("ocean", {})
    domain_cfg = config.get("domain", {})
    physics_cfg = config.get("physics", {})
    ic_cfg = config.get("initial_conditions", {})
    time_cfg = config.get("time", {})

    mode = config.get("experiment", {}).get("mode", "3d_ocean")

    if mode == "barotropic_ocean":
        raise NotImplementedError("Barotropic runner not yet implemented; use run_ocean_test_matrix.py")

    grid_type = grid_cfg.get("type", "latlon")
    resolution = grid_cfg.get("resolution", "64x128")

    return {
        "mode": mode,
        "grid_type": grid_type,
        "resolution": resolution,
        "ocean_config_dict": ocean_cfg,
        "domain": domain_cfg,
        "physics": physics_cfg,
        "initial_conditions": ic_cfg,
        "time": time_cfg,
    }


def init_experiment(
    template_name: str,
    experiment_name: str | None = None,
    overrides: list[str] | None = None,
    machine: str | None = None,
) -> Path:
    """Create an experiment directory from a template.

    Creates:
        experiments/<name>/config.yaml   — resolved config
        experiments/<name>/experiment.tag — reproducibility tag
        experiments/<name>/run.sh        — launch script
    """
    config = load_template(template_name)

    if overrides:
        config = apply_overrides(config, overrides)

    if experiment_name is None:
        experiment_name = config.get("experiment", {}).get("name", "untitled")

    exp_dir = EXPERIMENTS_DIR / experiment_name
    exp_dir.mkdir(parents=True, exist_ok=True)

    config_path = exp_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    tag = generate_tag(config, template_name, machine)
    tag_path = exp_dir / "experiment.tag"
    with open(tag_path, "w") as f:
        f.write(tag)

    run_script = _generate_run_script(config, exp_dir, machine)
    run_path = exp_dir / "run.sh"
    with open(run_path, "w") as f:
        f.write(run_script)

    return exp_dir


def generate_tag(
    config: dict,
    template_name: str,
    machine: str | None = None,
) -> str:
    """Generate an experiment.tag string (INI format) for reproducibility."""
    version_info = load_version_info()
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode()
    ).hexdigest()

    import platform

    now = datetime.now(timezone.utc).isoformat()

    lines = [
        "[experiment]",
        f"name = {config.get('experiment', {}).get('name', 'unknown')}",
        f"template = {template_name}",
        f"mode = {config.get('experiment', {}).get('mode', 'unknown')}",
        f"created = {now}",
        "",
        "[legoESM]",
        f"ref = {version_info.get('ref', 'unknown')}",
        f"commit = {version_info.get('commit', 'unknown')}",
    ]

    patches = sorted(PATCHES_DIR.glob("*.patch"))
    if patches:
        lines.append(f"patches = {','.join(p.name for p in patches)}")

    lines += [
        "",
        "[model]",
        f"configuration = {config.get('experiment', {}).get('mode', 'unknown')}",
    ]
    grid = config.get("grid", {})
    if grid:
        lines.append(f"grid_type = {grid.get('type', 'unknown')}")
        lines.append(f"resolution = {grid.get('resolution', 'unknown')}")
        nlev = grid.get("n_levels", grid.get("nlev", "unknown"))
        lines.append(f"nlev = {nlev}")

    lines += [
        "",
        "[run]",
    ]
    time_cfg = config.get("time", {})
    if "duration_days" in time_cfg:
        lines.append(f"duration_days = {time_cfg['duration_days']}")
    if "dt_seconds" in time_cfg:
        lines.append(f"dt_seconds = {time_cfg['dt_seconds']}")

    lines += [
        "",
        "[machine]",
        f"hostname = {platform.node()}",
        f"machine_config = {machine or 'default'}",
    ]

    lines += [
        "",
        "[reproducibility]",
        f"config_hash = sha256:{config_hash[:16]}",
        f"legoesm_ref = {version_info.get('ref', 'unknown')}",
        f"python_version = {platform.python_version()}",
    ]

    try:
        import jax
        lines.append(f"jax_version = {jax.__version__}")
    except ImportError:
        lines.append("jax_version = not_installed")

    return "\n".join(lines)


def _generate_run_script(config: dict, exp_dir: Path, machine: str | None = None) -> str:
    """Generate a shell launch script for the experiment."""
    mode = config.get("experiment", {}).get("mode", "unknown")
    template = config.get("experiment", {}).get("name", "unknown")

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f"# Auto-generated run script for experiment: {template}",
        f"# Mode: {mode}",
        f"# Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]

    machine_cfg_path = ""
    if machine:
        machine_cfg_path = str(Path(__file__).resolve().parent.parent / "machines" / f"{machine}.yaml")
        lines.append(f"# Machine config: {machine_cfg_path}")
        lines.append(f"LEGOESM_MACHINE_CONFIG={machine_cfg_path}")
        lines.append("")

    lines += [
        'EXPERIMENT_DIR=$(cd "$(dirname "$0")" && pwd)',
        'CONFIG="$EXPERIMENT_DIR/config.yaml"',
        "",
        "# Source machine environment if available",
        'if [ -n "${LEGOESM_MACHINE_CONFIG:-}" ] && [ -f "$LEGOESM_MACHINE_CONFIG" ]; then',
        "    # Parse machine YAML for env_setup commands",
        '    echo "Loading machine config: $LEGOESM_MACHINE_CONFIG"',
        "fi",
        "",
        "# Resolve legoESM",
        f"LEGOESM_DIR={os.environ.get('LEGOESM_DIR', str(Path(__file__).resolve().parent.parent.parent / 'legoESM'))}",
        'export PYTHONPATH="$LEGOESM_DIR/src:$PYTHONPATH"',
        "",
        "# Run the experiment",
        'python -m runners.run_experiment run "$CONFIG"',
        "",
    ]

    if mode.startswith("3d_ocean") or mode == "barotropic_ocean" or mode == "ocean_scm":
        lines += [
            "# For ocean experiments, you can also use the test matrix runner:",
            "# python -m runners.run_ocean_test_matrix --template " + template,
        ]

    return "\n".join(lines)


def run_experiment(config_path: Path, legoesm_path: Path | None = None):
    """Execute an experiment from a resolved config.yaml file."""
    if legoesm_path is None:
        legoesm_path = resolve_legoesm_path()

    with open(config_path) as f:
        config = yaml.safe_load(f)

    mode = detect_mode(config)

    print(f"Running experiment: {config.get('experiment', {}).get('name', 'unknown')}")
    print(f"Mode: {mode}")
    print(f"legoESM: {legoesm_path}")

    if mode == "atmosphere_only":
        exp = build_atmosphere_config(config, legoesm_path)
        sys.path.insert(0, str(legoesm_path / "src"))
        from legoesm.driver.model_driver import ModelDriver
        driver = ModelDriver(exp)
        driver.setup()
        driver.run()
    elif mode in ("3d_ocean", "3d_ocean_realistic", "barotropic_ocean", "ocean_scm"):
        _run_ocean(config, legoesm_path)
    elif mode == "coupled":
        _run_coupled(config, legoesm_path)
    else:
        raise ValueError(f"Unknown mode: {mode}")


def _run_ocean(config: dict, legoesm_path: Path):
    """Run an ocean experiment using the legoesm ocean model directly."""
    sys.path.insert(0, str(legoesm_path / "src"))

    from legoesm.ocean.state import LatLonCGridOceanConfig
    from legoesm.ocean.experiments import get_experiment
    import jax
    import jax.numpy as jnp

    mode = config.get("experiment", {}).get("mode", "3d_ocean")
    case = config.get("ocean", {}).get("case", "rest_state")
    grid_type = config.get("grid", {}).get("type", "latlon")

    exp_info = get_experiment(case)

    print(f"Ocean experiment: case={case}, grid={grid_type}")
    print(f"  Scientific purpose: {exp_info.get('scientific_purpose', 'N/A')}")

    print("NOTE: Full ocean experiment execution requires case-specific Python code.")
    print("      Use run_ocean_test_matrix.py for pre-built test harnesses.")
    print("      The config.yaml and experiment.tag have been generated for reproducibility.")


def _run_coupled(config: dict, legoesm_path: Path):
    """Run a coupled ESM experiment."""
    sys.path.insert(0, str(legoesm_path / "src"))

    from legoesm.driver.coupled_config import (
        preset_aquaplanet,
        preset_slab_simple,
        preset_slab_richards,
        preset_full_coupled,
    )

    preset_name = config.get("coupled", {}).get("preset", "aquaplanet")
    presets = {
        "aquaplanet": preset_aquaplanet,
        "slab_simple": preset_slab_simple,
        "slab_richards": preset_slab_richards,
        "full_coupled": preset_full_coupled,
    }

    if preset_name not in presets:
        raise ValueError(f"Unknown coupled preset: {preset_name}")

    atm_config = build_atmosphere_config(config, legoesm_path)
    coupled_cfg = presets[preset_name]()

    print(f"Running coupled experiment with preset: {preset_name}")
    from legoesm.driver.coupled_esm_driver import CoupledESMDriver
    driver = CoupledESMDriver(atm_config, coupled_cfg)
    driver.setup()
    driver.run()


def main():
    parser = argparse.ArgumentParser(description="legoESM ocean experiment runner")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    run_p = subparsers.add_parser("run", help="Run an experiment from config.yaml")
    run_p.add_argument("config", type=Path, help="Path to config.yaml")

    init_p = subparsers.add_parser("init", help="Initialize an experiment from a template")
    init_p.add_argument("template", help="Template name (e.g. 3d_idealized/baroclinic_gyre)")
    init_p.add_argument("--name", help="Experiment name (default: from template)")
    init_p.add_argument("-o", "--override", action="append", default=[], help="Override (key=value)")
    init_p.add_argument("--machine", help="Machine config name")

    tag_p = subparsers.add_parser("tag", help="Generate a tag file for a config")
    tag_p.add_argument("config", type=Path, help="Path to config.yaml")
    tag_p.add_argument("--template", default="unknown", help="Template name")

    args = parser.parse_args()

    if args.command == "run":
        run_experiment(args.config)
    elif args.command == "init":
        exp_dir = init_experiment(args.template, args.name, args.override, args.machine)
        print(f"Experiment initialized: {exp_dir}")
        print(f"  config.yaml:  {exp_dir / 'config.yaml'}")
        print(f"  experiment.tag: {exp_dir / 'experiment.tag'}")
        print(f"  run.sh:  {exp_dir / 'run.sh'}")
    elif args.command == "tag":
        with open(args.config) as f:
            config = yaml.safe_load(f)
        tag = generate_tag(config, args.template)
        print(tag)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()