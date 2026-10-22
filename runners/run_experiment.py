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
CATALOG_FILE = Path(__file__).resolve().parent.parent / "data_catalog.yaml"

# Matrix-lane dispatch: ocean.case -> (grid.type -> upstream matrix --grid
# value). Module-level because it is the single source of truth for two
# consumers: _run_ocean (run dispatch) and scripts/validate_templates.py's
# consistency gate (grid-family agreement with the upstream counterpart).
_MATRIX_CASES = {
    "baroclinic_gyre": {"latlon": "latlon_regional",
                        "mpas": "mpas_regional"},
    "lock_exchange": {"latlon": "latlon"},
    "overflow": {"latlon": "latlon"},
    "acc_channel": {"latlon": "latlon_channel",
                    "mpas": "mpas_channel"},
    "geostrophic_adjustment": {"latlon": "latlon"},
    "phillips_two_layer": {"latlon": "latlon"},
    "global_overturning": {"latlon": "latlon"},
    "neverworld2_lite": {"latlon": "latlon"},
    "eady_instability": {"latlon": "latlon_channel"},
    "rest_state_stratified_no_land": {"latlon": "latlon"},
    "barotropic_wave": {"latlon": "latlon"},
    "barotropic_double_gyre": {"latlon": "latlon_regional"},
}


def load_catalog() -> dict:
    """Load the data catalog YAML."""
    with open(CATALOG_FILE) as f:
        return yaml.safe_load(f)


def resolve_data_root() -> Path:
    """Find the data root directory.

    Search order:
    1. LEGOESM_DATA_DIR environment variable
    2. ./data (relative to this repo)
    """
    env_dir = os.environ.get("LEGOESM_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(__file__).resolve().parent.parent / "data"


_RUNNERS_ROOT = Path(__file__).resolve().parent.parent


def _get_current_tag() -> str:
    """Current legoesm-* tag at HEAD, or 'untagged@<sha>' in the untagged window.

    A bare "untagged" loses the runners layer entirely; the commit fallback
    keeps a resolvable identity (reproduce.py checks it out directly).
    """
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            capture_output=True, text=True, cwd=_RUNNERS_ROOT,
        )
        if result.returncode == 0:
            tag = result.stdout.strip()
            if tag.startswith("legoesm-"):
                return tag
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=_RUNNERS_ROOT,
        )
        if sha.returncode == 0:
            return f"untagged@{sha.stdout.strip()}"
        return "untagged"
    except Exception:
        return "untagged"


def resolve_data_paths(requires: list[str], data_root: Path | None = None) -> dict[str, Path]:
    """Resolve template requires IDs to absolute file paths.

    Returns a dict mapping catalog ID -> absolute Path.
    Raises FileNotFoundError if a required file is missing.
    """
    if data_root is None:
        data_root = resolve_data_root()

    catalog = load_catalog()
    catalog_files = catalog.get("files", {})
    paths = {}

    for file_id in requires:
        if file_id not in catalog_files:
            raise KeyError(f"Data catalog entry not found: {file_id}")

        entry = catalog_files[file_id]
        path = data_root / entry["path"]

        if entry.get("access") == "derived":
            derived_root = path
            if derived_root.is_dir():
                paths[file_id] = derived_root
            elif derived_root.exists():
                paths[file_id] = derived_root
            else:
                paths[file_id] = derived_root
        else:
            paths[file_id] = path

    return paths


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
            # YAML-style scalars: ast.literal_eval only knows Python literals
            # (True/False/None), so 'false'/'true' would otherwise stay
            # strings and read as truthy downstream.
            low = value_str.strip().lower()
            value = {"true": True, "false": False, "null": None}.get(low,
                                                                    value_str)
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
    output_dir: Path | None = None,
) -> Path:
    """Create an experiment directory from a template.

    Creates:
        <output_dir>/config.yaml   — resolved config
        <output_dir>/experiment.tag — reproducibility tag
        <output_dir>/run.sh        — launch script

    ``output_dir`` is required — files are written there directly.
    """
    if output_dir is None:
        raise ValueError("--output-dir is required (e.g. runs/<experiment-name>/)")

    config = load_template(template_name)

    if overrides:
        config = apply_overrides(config, overrides)

    requires_patches = config.get("requires_patches", [])
    if requires_patches:
        missing = [p for p in requires_patches if not (PATCHES_DIR / p).exists()]
        if missing:
            print(f"WARNING: Template requires patches not found in patches/:")
            for p in missing:
                print(f"  - {p}")
            print("  Apply them with: bash scripts/apply_patches.sh")
        else:
            print(f"All required patches present: {', '.join(requires_patches)}")

    if experiment_name is None:
        experiment_name = config.get("experiment", {}).get("name", "untitled")

    exp_dir = output_dir
    exp_dir.mkdir(parents=True, exist_ok=True)

    config_path = exp_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    tag = generate_tag(config, template_name, machine, overrides=overrides)
    tag_path = exp_dir / "experiment.tag"
    with open(tag_path, "w") as f:
        f.write(tag)

    run_script = _generate_run_script(config, exp_dir, machine, template_name)
    run_path = exp_dir / "run.sh"
    with open(run_path, "w") as f:
        f.write(run_script)
    # Executable: scheduler -S submissions (oarsub -S ./run.sh) execute
    # the script directly and need the exec bit (bigfoot NW2 208303,
    # 2026-10-10: "Permission denied" on a 644 run.sh).
    run_path.chmod(0o755)

    return exp_dir


def generate_tag(
    config: dict,
    template_name: str,
    machine: str | None = None,
    overrides: list[str] | None = None,
) -> str:
    """Generate an experiment.tag string (INI format) for reproducibility.

    ``overrides`` is the raw CLI override list (``key=value`` strings) as
    passed to init; recorded under ``[reproducibility]`` so reproduce.py can
    re-apply them (without it, a reproduced run silently falls back to
    template defaults). NOTE: ``config`` must ALREADY have the overrides
    applied (as ``init_experiment`` does) — this parameter only RECORDS
    them; passing an un-overridden config with ``overrides`` produces a tag
    whose config_hash contradicts its own recorded overrides, and
    ``reproduce.py --verify`` will (correctly) reject it.
    """
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
        # Content digests: a filename can be reused with different content
        # (patch edited, pin bumped); the sha256 pins what init actually saw.
        for p in patches:
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            lines.append(f"patch_sha256_{p.stem} = sha256:{digest[:16]}")

    requires_patches = config.get("requires_patches", [])
    if requires_patches:
        lines.append(f"requires_patches = {','.join(requires_patches)}")

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
    # Recipe identity: the named scheme identity the run lane assembles
    # (AGENTS.md "Recipes"). Absent = the lane's own default identity
    # (e.g. dino without ocean.recipe runs the upstream DINOConfig
    # paper-faithful defaults).
    recipe = (config.get("ocean") or {}).get("recipe")
    if recipe:
        lines.append(f"recipe = {recipe}")

    lines += [
        "",
        "[run]",
    ]
    time_cfg = config.get("time", {})
    if "duration_days" in time_cfg:
        lines.append(f"duration_days = {time_cfg['duration_days']}")
    if "dt_seconds" in time_cfg:
        lines.append(f"dt_seconds = {time_cfg['dt_seconds']}")

    requires = config.get("requires", [])
    if requires:
        lines += [
            "",
            "[data]",
            f"data_root = {str(resolve_data_root())}",
            f"requires = {','.join(requires)}",
        ]
        data_paths = resolve_data_paths(requires)
        for file_id, path in data_paths.items():
            lines.append(f"{file_id} = {path}")

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
    ]

    try:
        runner_tag = _get_current_tag()
        lines.append(f"runner_tag = {runner_tag}")
    except Exception:
        lines.append("runner_tag = untagged")

    # Raw override list (JSON) — the missing link for reproduce.py --run.
    # Only when actually given: a template-defaults run records nothing,
    # and the absence itself is the (true) statement.
    if overrides:
        lines.append(f"overrides = {json.dumps(overrides)}")

    lines.append(f"python_version = {platform.python_version()}")

    try:
        import jax
        lines.append(f"jax_version = {jax.__version__}")
    except ImportError:
        lines.append("jax_version = not_installed")

    return "\n".join(lines)


def _load_machine_config(machine: str | None) -> dict | None:
    """Load machine config YAML if a path or name is given. Returns None if not available."""
    if not machine:
        return None
    machine_path = Path(machine)
    if not machine_path.is_absolute() and "/" not in machine:
        # Bare name: search the runners' own machines/ dir first, then the
        # sibling experiments repo (machine configs live in
        # my-legoESM-ocean-experiments/machines/ per workspace conventions).
        runners_dir = Path(__file__).resolve().parent.parent
        machine_path = runners_dir / "machines" / f"{machine}.yaml"
        experiments_dir = (runners_dir.parent / "my-legoESM-ocean-experiments"
                           / "machines" / f"{machine}.yaml")
        if not machine_path.is_file() and experiments_dir.is_file():
            machine_path = experiments_dir
    if machine_path.is_file():
        with open(machine_path) as f:
            return yaml.safe_load(f)
    print(f"WARNING: machine config {machine!r} not found "
          f"(looked for {machine_path}); continuing without machine settings.")
    return None


def _generate_run_script(config: dict, exp_dir: Path, machine: str | None = None,
                         template_name: str | None = None) -> str:
    """Generate a shell launch script for the experiment."""
    mode = config.get("experiment", {}).get("mode", "unknown")
    template = config.get("experiment", {}).get("name", "unknown")
    machine_cfg = _load_machine_config(machine)

    scheduler = machine_cfg.get("scheduler") if machine_cfg else None

    # NOTE: scheduler directives (#SBATCH / #OAR) MUST precede the first
    # non-comment line (slurm stops parsing the directive header at the first
    # command). The `set -euo pipefail` line therefore comes AFTER the whole
    # scheduler block; putting it first made jean-zay submissions fall back
    # to defaults ("Multiple accounts available", unfilled partition/qos,
    # 2026-10-08).
    scheduler_lines: list[str] = []
    if scheduler == "slurm":
        scheduler_lines += ["# ---------- SLURM directives ----------"]
        scheduler_lines.append(f"#SBATCH --job-name={template}")
        partition = machine_cfg.get("scheduler_partition", "")
        if partition:
            scheduler_lines.append(f"#SBATCH --partition={partition}")
        account = machine_cfg.get("scheduler_account", "")
        if account:
            scheduler_lines.append(f"#SBATCH --account={account}")
        nodes = machine_cfg.get("scheduler_nodes", 1)
        scheduler_lines.append(f"#SBATCH --nodes={nodes}")
        tasks_per_node = machine_cfg.get("scheduler_tasks_per_node", 1)
        scheduler_lines.append(f"#SBATCH --ntasks-per-node={tasks_per_node}")
        # Memory on clusters that forbid --mem (jean-zay) derives per-CPU:
        # MinMemoryPerCPU x cpus. A GPU card with 1 task and no cpus-per-task
        # claims only ~2-7 GB host bound and gets OOM-killed by any big
        # XLA compile (jean-zay forensics 2026-10-09: jobs 764059/782995/
        # 801848/803209/808917, rc=137 pre-first-diag). scheduler_cpus_per_task
        # claims whole-node CPUs for the single task; WITHOUT it the default
        # is the cluster's MinMemoryPerCPU share only.
        cpus_per_task = machine_cfg.get("scheduler_cpus_per_task")
        if cpus_per_task:
            scheduler_lines.append(f"#SBATCH --cpus-per-task={cpus_per_task}")
        walltime = machine_cfg.get("scheduler_walltime", "01:00:00")
        scheduler_lines.append(f"#SBATCH --time={walltime}")
        mem = machine_cfg.get("scheduler_mem", "")
        if mem:
            scheduler_lines.append(f"#SBATCH --mem={mem}")
        gres = machine_cfg.get("scheduler_gres", "")
        if gres:
            scheduler_lines.append(f"#SBATCH --gres={gres}")
        constraint = machine_cfg.get("scheduler_constraint", "")
        if constraint:
            scheduler_lines.append(f"#SBATCH -C {constraint}")
        qos = machine_cfg.get("scheduler_qos", "")
        if qos:
            scheduler_lines.append(f"#SBATCH --qos={qos}")
        out_pattern = machine_cfg.get("scheduler_output", "")
        if out_pattern:
            scheduler_lines.append(f"#SBATCH --output={out_pattern}")
        err_pattern = machine_cfg.get("scheduler_error", "")
        if err_pattern:
            scheduler_lines.append(f"#SBATCH --error={err_pattern}")
        scheduler_lines.append("")

    elif scheduler == "oar":
        # OAR (GRICAD/CIMENT: bigfoot, dahu; kraken runs OAR v3 — same CLI).
        # `oarsub -S run.sh` parses #OAR directives like sbatch parses
        # #SBATCH, making the manual wrapper pattern native (ledger
        # bigfoot_2026-10-08_tripole-gpu-smoke, OAR 207904):
        #   cd <experiment-dir> && oarsub -S run.sh
        # Job logs land as OAR.<name>.<jobid>.stdout/.stderr in the
        # submission directory; monitor with `oarstat -u`.
        scheduler_lines += ["# ---------- OAR directives ----------"]
        scheduler_lines.append(f"#OAR -n {template}")
        project = machine_cfg.get("oar_project", "")
        if project:
            scheduler_lines.append(f"#OAR --project {project}")
        resources = machine_cfg.get("oar_resources", "/nodes=1")
        walltime = machine_cfg.get("scheduler_walltime", "01:00:00")
        if "walltime" not in resources:
            resources = f"{resources},walltime={walltime}"
        scheduler_lines.append(f"#OAR -l {resources}")
        properties = machine_cfg.get("oar_properties", "")
        if properties:
            # NOTE: no shell-style quoting here — OAR's -S directive parser
            # (oar/lib/submission.py) captures the -p value VERBATIM, so
            # wrapping quotes would reach the server as invalid SQL and
            # abort the submission transaction (bigfoot OAR 3.0.3b1,
            # InFailedSqlTransaction, 2026-10-10). Command-line -p keeps
            # its usual quoting; only the #OAR directive form is bare.
            scheduler_lines.append(f"#OAR -p {properties}")
        job_types = machine_cfg.get("oar_types", [])
        if isinstance(job_types, str):
            job_types = [job_types]
        for job_type in job_types:
            scheduler_lines.append(f"#OAR -t {job_type}")
        out_pattern = machine_cfg.get("scheduler_output", "")
        if out_pattern:
            scheduler_lines.append(f"#OAR -O {out_pattern}")
        err_pattern = machine_cfg.get("scheduler_error", "")
        if err_pattern:
            scheduler_lines.append(f"#OAR -E {err_pattern}")
        scheduler_lines.append("")

    lines = [
        "#!/usr/bin/env bash",
        *scheduler_lines,
        "set -euo pipefail",
        "",
        f"# Auto-generated run script for experiment: {template}",
        f"# Mode: {mode}",
        f"# Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]

    body: list[str] = []

    machine_cfg_path = ""
    if machine:
        if Path(machine).is_absolute() or "/" in machine:
            machine_cfg_path = machine
        else:
            machine_cfg_path = str(Path(__file__).resolve().parent.parent / "machines" / f"{machine}.yaml")
        body.append(f"# Machine config: {machine_cfg_path}")
        body.append(f"LEGOESM_MACHINE_CONFIG={machine_cfg_path}")
        body.append("")

    lines += [
        # sbatch runs a COPY of this script from /var/spool/slurmd/<job>/, so
        # $0-relative resolution lands in the spool (job 761687). Embed the
        # absolute init-time directory and fall back to $0 only if it moved.
        f"EXPERIMENT_DIR={exp_dir.resolve()}",
        '[ -f "$EXPERIMENT_DIR/config.yaml" ] || '
        'EXPERIMENT_DIR=$(cd "$(dirname "$0")" && pwd)',
        'CONFIG="$EXPERIMENT_DIR/config.yaml"',
        f"CONFIG_TEMPLATE={template_name!r}",
        # The runner + its CLI tools are repo-relative; anchor the repo root
        # so the script works from ANY cwd (experiment dir, spool, home).
        f"RUNNERS_ROOT={_RUNNERS_ROOT}",
        'cd "$RUNNERS_ROOT"',
        "",
        *body,
    ]

    env_setup = machine_cfg.get("env_setup", []) if machine_cfg else []
    if env_setup:
        lines.append("# ---------- Machine environment setup ----------")
        for cmd in env_setup:
            lines.append(cmd)
        lines.append("")

    data_root = machine_cfg.get("data_root", "") if machine_cfg else ""
    if data_root:
        lines.append(f"# Data root (from machine config: {machine_cfg_path})")
        lines.append(f'DATA_ROOT=${{LEGOESM_DATA_DIR:-{data_root}}}')
    else:
        lines.append("# Resolve data root")
        lines.append(f'DATA_ROOT=${{LEGOESM_DATA_DIR:-{resolve_data_root()}}}')
    lines.append('export LEGOESM_DATA_DIR="$DATA_ROOT"')
    lines.append("")

    lines += [
        "# Check data availability before running",
        'python scripts/fetch_data.py check "$CONFIG_TEMPLATE" --data-dir "$DATA_ROOT" || {',
        '    echo "ERROR: Missing required data files. Run: python scripts/fetch_data.py fetch $CONFIG_TEMPLATE"',
        '    exit 1',
        '}',
        "",
    ]

    legoesm_dir = machine_cfg.get("legoesm_dir", "") if machine_cfg else ""
    if legoesm_dir:
        lines.append(f"# legoESM dir (from machine config: {machine_cfg_path})")
        lines.append(f"LEGOESM_DIR={legoesm_dir}")
    else:
        lines.append("# Resolve legoESM")
        lines.append(f"LEGOESM_DIR={os.environ.get('LEGOESM_DIR', str(Path(__file__).resolve().parent.parent.parent / 'legoESM'))}")
    lines.append("# legoESM must be installed (uv sync or pip install -e .)")
    lines.append("")

    # Orchestrator provenance (issue #8, Phase 2A): legoESM's
    # build_run_manifest() records these in [reproducibility] of the run's
    # run_manifest.json — the run-time truth of the runners layer (repo
    # state + patch chain at launch), complementary to experiment.tag's
    # init-time snapshot. Computed at RUN time, not embedded at init: if the
    # repo moved between init and launch, the manifest reports what ran.
    lines += [
        "# ---------- Orchestrator provenance (run_manifest.json) ----------",
        '_runner_tag="$(git -C "$RUNNERS_ROOT" describe --tags --exact-match HEAD 2>/dev/null || true)"',
        'case "$_runner_tag" in',
        "    legoesm-*) ;;",
        '    *) _runner_tag="untagged@$(git -C "$RUNNERS_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)" ;;',
        "esac",
        'export LEGOESM_RUNNER_TAG="$_runner_tag template=$CONFIG_TEMPLATE"',
        '_patch_list=""',
        'for _p in "$RUNNERS_ROOT"/patches/*.patch; do',
        '    [ -e "$_p" ] || continue',
        '    _patch_list="${_patch_list:+$_patch_list,}$(basename "$_p")"',
        "done",
        'export LEGOESM_RUNNER_PATCHES="$_patch_list"',
        "",
    ]

    mpi_cfg = config.get("mpi", {})
    mpi_enabled = mpi_cfg.get("enabled", False)

    if mpi_enabled:
        lines.append("# ---------- MPI environment ----------")
        lines.append("export OMP_NUM_THREADS=1")
        lines.append('export XLA_FLAGS="--xla_cpu_multi_thread_eigen=false"')
        lines.append("")
        mpi_ranks = mpi_cfg.get("ranks", 1)
        mpi_launcher = mpi_cfg.get("launcher", "mpirun")
        mpi_extra = mpi_cfg.get("extra_args", "")
        mpi_cmd_parts = [mpi_launcher, "-np", str(mpi_ranks)]
        if mpi_extra:
            mpi_cmd_parts.extend(mpi_extra.split())
        mpi_prefix = " ".join(mpi_cmd_parts)
        lines += [
            "# Run the experiment (MPI)",
            f'{mpi_prefix} python -m runners.run_experiment run "$CONFIG"',
            "",
        ]
    else:
        lines += [
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

    if mode in ("3d_ocean", "3d_ocean_realistic", "barotropic_ocean", "ocean_scm"):
        _run_ocean(config, legoesm_path, config_path)
    elif mode == "coupled":
        _run_coupled(config, legoesm_path)
    else:
        raise ValueError(f"Unknown mode: {mode}")


def _run_ocean(config: dict, legoesm_path: Path, config_path: Path | None = None):
    """Run an ocean experiment using the legoesm ocean model directly."""

    mode = config.get("experiment", {}).get("mode", "3d_ocean")

    if mode == "ocean_scm":
        from runners.run_ocean_scm import run_ocean_scm
        if config_path is None:
            config_path = Path("config.yaml")
        run_ocean_scm(config_path)
        return

    grid_type = config.get("grid", {}).get("type", "latlon")

    if mode == "3d_ocean_realistic" and grid_type == "tripole":
        _run_tripolar_omip(config, legoesm_path, config_path)
        return

    # 3D idealized case dispatch: case -> handler. Cases without a handler
    # fall through to the structural stub (init/provenance only).
    # barotropic_ocean matrix lanes (2d/) route through the same upstream
    # runner — the ocean test matrix executes them with the same 3D model
    # machinery.
    case = config.get("ocean", {}).get("case")
    if mode == "3d_ocean" and case == "dino" and grid_type == "latlon":
        _run_dino(config, legoesm_path, config_path)
        return
    if mode == "3d_ocean" and case == "bench" and grid_type in ("latlon", "tripole"):
        _run_bench(config, legoesm_path, config_path)
        return
    if (mode in ("3d_ocean", "barotropic_ocean")
            and case in _MATRIX_CASES
            and grid_type in _MATRIX_CASES[case]):
        _run_matrix_case(config, legoesm_path, config_path,
                         _MATRIX_CASES[case][grid_type])
        return

    from legoesm.ocean.experiments import AVAILABLE_EXPERIMENTS

    exp_info = AVAILABLE_EXPERIMENTS.get(case)
    if exp_info is None:
        print(f"Ocean experiment: case={case!r} (not in legoESM AVAILABLE_EXPERIMENTS), grid={grid_type}")
    else:
        print(f"Ocean experiment: case={case}, grid={grid_type}")
        print(f"  Scientific purpose: {exp_info.get('scientific_purpose', 'N/A')}")

    print("NOTE: Full ocean experiment execution requires case-specific Python code.")
    print("      Use run_ocean_test_matrix.py for pre-built test harnesses.")
    print("      The config.yaml and experiment.tag have been generated for reproducibility.")


def _run_tripolar_omip(config: dict, legoesm_path: Path, config_path: Path | None = None):
    """Run a tripolar OMIP experiment via script delegation to run_omip_core2.py."""
    import subprocess
    from runners.mpi_utils import get_mpi_config, build_mpi_launch_command

    grid_cfg = config.get("grid", {})
    ocean_cfg = config.get("ocean", {})
    time_cfg = config.get("time", {})
    forcing_cfg = config.get("forcing", {})
    physics_cfg = config.get("physics", {})
    output_cfg = config.get("output", {})
    ic_cfg = config.get("initial_conditions", {})
    scan_cfg = config.get("scan", {})

    mpi_cfg = get_mpi_config(config)
    if mpi_cfg["enabled"]:
        script = str(legoesm_path / "scripts" / "run" / "run_omip_core2_mpi.py")
    else:
        script = str(legoesm_path / "scripts" / "run" / "run_omip_core2.py")
    data_root = resolve_data_root()

    duration_days = time_cfg.get("duration_days", 3650)
    # +0.05 d overshoot on the standard faithful card: the driver SKIPS the
    # cadence snapshot at the exact final step, so the advertised day-N
    # snapshot only lands as a normal cadence write with a small overshoot
    # (codex HIGH finding on the standard card). Default 0.0 = exactly like
    # a hand-built --years invocation.
    duration_overshoot_days = float(time_cfg.get("duration_overshoot_days", 0.0))
    # Upstream build_tripole (pin c986cb989) asserts that --mesh resolves to
    # the canonical repo-relative data/grids/<file> path: it derives the
    # resolution from the mesh filename and builds the grid from the SAME
    # canonical path via run_omip._parse_resolution, then requires
    # Path.resolve() equality on both sides. Any $LEGOESM_DATA_DIR-rooted
    # absolute path fails that assert. So: run the delegated script with
    # cwd=legoesm_path and pass the repo-rooted mesh path — both sides then
    # resolve identically. The mesh must exist at <legoesm>/data/grids/
    # (a symlink to a data_root copy is fine: both sides resolve through it).
    mesh_arg = str(legoesm_path / "data" / "grids"
                   / grid_cfg.get("mesh_file", "eORCA1.2_mesh_mask.nc"))
    # The subprocess cwd becomes the legoESM repo, so a relative --output
    # would relocate: absolutize against the experiment directory.
    out_dir = config_path.parent if config_path else Path.cwd()
    output_arg = str(out_dir / output_cfg.get("path", "results/omip_tripole"))
    cmd = [
        sys.executable, script,
        "--dt", str(time_cfg.get("dt_seconds", 1200)),
        "--nlev", str(grid_cfg.get("nlev", 75)),
        "--mesh", mesh_arg,
        "--output", output_arg,
    ]

    if duration_days > 0 and duration_days < 365:
        cmd.extend(["--days", str(duration_days + duration_overshoot_days)])
    else:
        cmd.extend(["--years",
                    str((duration_days + duration_overshoot_days) / 365.0)])

    # Output cadence (upstream --snapshot-every-days / --diag-every-days).
    # NOTE: the+0.05 d duration overshoot above exists because the driver
    # SKIPS the cadence snapshot at the exact final step (codex HIGH on the
    # standard card: an exact-length run wrote only snapshot_final), so a
    # cadence-gridded snapshot at the advertised day always needs the
    # overshoot even when the number of steps is more than the cadence.
    snap_days = output_cfg.get("snapshot_every_days")
    if snap_days:
        cmd.extend(["--snapshot-every-days", str(snap_days)])
    diag_days = output_cfg.get("diag_every_days")
    if diag_days:
        cmd.extend(["--diag-every-days", str(diag_days)])

    if grid_cfg.get("partial_cells", False):
        cmd.append("--partial-cell")

    convection = physics_cfg.get("convection", "none")
    if convection and convection != "none":
        cmd.extend(["--convection", convection])

    # Vertical-mixing closure: upstream --tripole-vmix {none,tke,kpp} defaults
    # to none, silently ignoring the template's physics.vertical_mixing.
    vmix = (physics_cfg.get("vertical_mixing", {}) or {}).get("scheme", "none")
    if vmix and vmix != "none":
        cmd.extend(["--tripole-vmix", vmix])

    # GM/Redi: upstream tripole recipe ships it ON (kappa=600) unless
    # --no-gm-redi is passed, so an explicit disabled/none in the template
    # must map to the flag or the override is silently ignored.
    lateral = physics_cfg.get("lateral_mixing", {}) or {}
    if lateral.get("enabled") is False or lateral.get("scheme") == "none":
        cmd.append("--no-gm-redi")
    elif lateral.get("kappa_GM"):
        cmd.extend(["--gm-aei0", str(lateral["kappa_GM"])])

    # Bottom drag: scheme in {legacy, nemo_quadratic, nemo_loglayer} (template
    # 'linear' maps to the legacy linear-r path); the r/cd0/cdmax/z0/ke0
    # params map 1:1. Upstream defaults to OFF when the section is absent.
    bd = physics_cfg.get("bottom_drag", {}) or {}
    bd_scheme = bd.get("scheme")
    if bd_scheme and bd_scheme != "none":
        cmd.extend(["--bottom-drag-scheme",
                    "legacy" if bd_scheme == "linear" else bd_scheme])
    if bd.get("r") is not None:
        cmd.extend(["--bottom-drag-r", str(bd["r"])])
    for key, flag in (("cd0", "--bottom-drag-cd0"),
                      ("cdmax", "--bottom-drag-cdmax"),
                      ("z0", "--bottom-drag-z0"),
                      ("ke0", "--bottom-drag-ke0")):
        if bd.get(key) is not None:
            cmd.extend([flag, str(bd[key])])

    scan_block = scan_cfg.get("block_size", 0)
    if scan_block > 0 and not mpi_cfg["enabled"]:
        cmd.extend(["--scan-block", str(scan_block)])

    ic_type = ic_cfg.get("type", "woce")
    if ic_type == "woa":
        cmd.append("--woa-init")
    elif ic_type == "woce":
        cmd.extend([
            "--nemo-monthly-init",
            str(data_root / "ic" / "woce_temp_monthly_init_4p2.nc"),
            str(data_root / "ic" / "woce_salt_monthly_init_4p2.nc"),
        ])

    if forcing_cfg.get("synthetic", False):
        cmd.append("--synthetic-forcing")

    forcing_scale = forcing_cfg.get("scale", 1.0)
    if forcing_scale != 1.0:
        cmd.extend(["--forcing-scale", str(forcing_scale)])

    smag_safety = ocean_cfg.get("smag_cfl_safety", 0.0)
    if smag_safety > 0:
        cmd.extend(["--smag-cfl-safety", str(smag_safety)])

    C_smag_lap = ocean_cfg.get("C_smag_lap", 0.0)
    if C_smag_lap > 0:
        cmd.extend(["--C-smag-lap", str(C_smag_lap)])

    A_h = ocean_cfg.get("A_h", 0.0)
    if A_h > 0:
        cmd.extend(["--A-h", str(A_h)])

    if ocean_cfg.get("adaptive_implicit_vertadv", False):
        cmd.append("--adaptive-implicit-vertadv")

    sss_target = data_root / "sss" / "sss_climatology_for_restoring.nc"
    sss_cfg = physics_cfg.get("sss_restoring", {})
    if sss_cfg.get("enabled", False) and sss_target.exists():
        cmd.append("--sss-restore")
        cmd.extend(["--sss-restore-file", str(sss_target)])
        sss_tau = sss_cfg.get("tau_days", 60.0)
        if sss_tau != 60.0:
            cmd.extend(["--sss-restore-tau-days", str(sss_tau)])

    # Dai-Trenberth runoff (--runoff). NOTE: at pin c986cb989 upstream loads
    # it from a hardcoded path (_RUNOFF_NC) plus domain_cfg cell areas
    # (_NEMO_DOMAIN_CFG) — both /burg-archive/... — so this only works on
    # machines that have the NEMO orca1_inputs repository at those paths
    # until an env-override patch lands (Phase-3 item).
    if (forcing_cfg.get("runoff", {}) or {}).get("enabled", False):
        cmd.append("--runoff")

    # Verbatim passthrough (cards): `run.extra_args` list appended AFTER all
    # mapped args, in order, with only the {data_root} token substituted.
    # This is how the NEMO-faithful standard card is recorded: the flag list
    # is verbatim content of config.yaml + experiment.tag, and any flag the
    # mapping above (or patch extensions) adds forwards upstream flags
    # (_RUNOFF_NC override etc.) without reinterpreting them.
    extra_args = config.get("run", {}).get("extra_args") or []
    for raw in extra_args:
        cmd.append(str(raw).replace("{data_root}", str(data_root)))

    if mpi_cfg["enabled"]:
        cmd = build_mpi_launch_command(mpi_cfg, cmd)

    run_env = {**os.environ, "JAX_ENABLE_X64": "1"}
    if mpi_cfg["enabled"]:
        run_env.update({
            "OMP_NUM_THREADS": "1",
            "XLA_FLAGS": "--xla_cpu_multi_thread_eigen=false",
            "JAX_PLATFORMS": "cpu",
        })

    print(f"Running tripolar OMIP via: {' '.join(cmd)}")
    if mpi_cfg["enabled"]:
        print(f"  MPI: {mpi_cfg['ranks']} ranks, launcher={mpi_cfg['launcher']}")
    result = subprocess.run(cmd, env=run_env, cwd=str(legoesm_path))
    if result.returncode != 0:
        raise RuntimeError(f"run_omip_core2.py exited with code {result.returncode}")


# DINO scheme selections: (template key, upstream flag, valid choices,
# dino-template default). A flag is forwarded only when the resolved
# config differs from the template default — the same semantics as the
# --dt guard (defaults are no-ops: run_dino.py applies the DINOConfig
# paper values itself). This keeps ocean.recipe cards authoritative:
# template-default scheme values are never forwarded after a recipe, so
# the card's selections stand unless an experiment explicitly overrides
# a field (2026-10-11 P-A receipt: template defaults silently
# un-certified the nemo_dino_kamm_mlf card on ige-calcul1).
_DINO_SCHEME_FLAGS = (
    ("vmix", "--vmix", ("kpp", "tke", "constant", "richardson", "catke"), "kpp"),
    ("eos", "--eos", ("wright", "nemo_seos"), "wright"),
    ("gm_kappa_scheme", "--gm-kappa-scheme", ("visbeck", "treguier"), "visbeck"),
    ("bottom_drag_scheme", "--bottom-drag-scheme",
     ("legacy", "nemo_quadratic", "nemo_loglayer"), "legacy"),
)


def _dino_scheme_flags(ocean_cfg: dict) -> list[str]:
    """Build DINO scheme-selection CLI flags, forwarding only overrides."""
    flags: list[str] = []
    for key, flag, choices, default in _DINO_SCHEME_FLAGS:
        val = ocean_cfg.get(key)
        if val is None or val == default:
            continue
        if choices and val not in choices:
            raise ValueError(
                f"ocean.{key}={val!r} is not a valid {flag} choice "
                f"({choices})")
        flags.extend([flag, str(val)])
    return flags


def _run_dino(config: dict, legoesm_path: Path, config_path: Path | None = None):
    """Run a DINO experiment via script delegation to scripts/run/run_dino.py.

    The upstream script (legoESM PR climate-federation/legoESM#1926; runners patch
    ``006-dino-spmd-restart-timing.patch`` at pins before the merge) is the
    standalone DINO production driver: it builds the paper-faithful R1
    DINOConfig itself, so this mapping only forwards the knobs a template
    legitimately overrides — resolution, duration, output cadence, scheme
    selections, and the patch-006 lanes (SPMD devices, restart, seed,
    timing). Unknown physics is NOT interpreted here; use ``run.extra_args``
    for verbatim upstream flags. ``ocean.recipe`` selects an upstream
    recipe card; scheme flags are forwarded only when overridden, so the
    card stands (see ``_DINO_SCHEME_FLAGS``).
    """
    import subprocess

    grid_cfg = config.get("grid", {})
    ocean_cfg = config.get("ocean", {})
    time_cfg = config.get("time", {})
    output_cfg = config.get("output", {})
    run_cfg = config.get("run", {}) or {}

    script = str(legoesm_path / "scripts" / "run" / "run_dino.py")
    if not Path(script).exists():
        raise FileNotFoundError(
            f"{script} not found — the DINO lane needs legoESM's "
            f"scripts/run/run_dino.py (check the pin / legoESM checkout)")

    # The subprocess cwd becomes the legoESM repo (relative --output would
    # relocate): absolutize against the experiment directory.
    out_dir = config_path.parent if config_path else Path.cwd()
    output_arg = str(out_dir / output_cfg.get("path", "results/dino"))

    cmd = [sys.executable, script, "--output", output_arg]

    # Resolution: n_lon drives the Mercator row count (50 -> 198 = R1).
    n_lon = grid_cfg.get("n_lon",
                         int(str(grid_cfg.get("resolution", "50x198")).split("x")[0])
                         if "x" in str(grid_cfg.get("resolution", "")) else 50)
    cmd.extend(["--n-lon", str(n_lon)])

    # Duration + cadence. The upstream script caps --days at 365 unless
    # --allow-multiyear is passed (a local-machine guard): durations over
    # a year (SLURM jobs) need the opt-out, forwarded automatically.
    duration_days = float(time_cfg.get("duration_days", 365))
    cmd.extend(["--days", str(duration_days)])
    if duration_days > 365.0:
        cmd.append("--allow-multiyear")
    snap_days = (output_cfg.get("snapshot_every_days")
                 or time_cfg.get("snapshot_every_days"))
    if snap_days:
        cmd.extend(["--snapshot-every-days", str(snap_days)])
    dt = time_cfg.get("dt_seconds")
    if dt is not None and dt != 2700:
        cmd.extend(["--dt", str(dt)])

    # Scheme selections: forwarded only when the template default was
    # overridden, so ocean.recipe cards stand (see _DINO_SCHEME_FLAGS).
    cmd.extend(_dino_scheme_flags(ocean_cfg))

    recipe = ocean_cfg.get("recipe")
    if recipe:
        cmd.extend(["--recipe", str(recipe)])
    if grid_cfg.get("nemo_faithful", ocean_cfg.get("nemo_faithful", False)):
        cmd.append("--nemo-faithful-grid")

    if config.get("physics", {}).get("disabled", False):
        cmd.append("--physics-off")
    if (config.get("forcing", {}) or {}).get("disabled", False):
        cmd.append("--no-forcing")

    # Patch-006 lanes (present upstream after PR #1926 merges; absent at
    # pins without the patch — check the flag exists before relying on it).
    nd = run_cfg.get("n_devices")
    if nd:
        cmd.extend(["--n-devices", str(nd)])
    restart_from = run_cfg.get("restart_from")
    if restart_from:
        # Resolve against the experiment dir (snapshot paths in run.yaml
        # are written relative to the experiment directory).
        rp = Path(restart_from)
        if not rp.is_absolute():
            rp = out_dir / rp
        cmd.extend(["--restart-from", str(rp)])
    seed = run_cfg.get("seed")
    if seed:
        cmd.extend(["--seed", str(seed)])
    if run_cfg.get("timing_jsonl"):
        cmd.extend(["--timing-jsonl", str(out_dir / str(run_cfg["timing_jsonl"]))])

    # Verbatim passthrough: run.extra_args appended AFTER the mapped args,
    # with only the {data_root} token substituted (the tripolar-card
    # convention — machine-portable, recorded verbatim in config.yaml).
    data_root = resolve_data_root()
    for raw in (run_cfg.get("extra_args") or []):
        cmd.append(str(raw).replace("{data_root}", str(data_root)))

    run_env = {**os.environ, "JAX_ENABLE_X64": "1"}
    print(f"Running DINO via: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=run_env, cwd=str(legoesm_path))
    if result.returncode != 0:
        raise RuntimeError(f"run_dino.py exited with code {result.returncode}")


# Measured-stable first-guess dt per BENCH preset (legoESM BENCH_PRESETS,
# stability probes committed 2026-10-10, boundary halved for margin).
_BENCH_PRESET_DT = {
    "orca1_like": 1200.0,
    "orca025_like": 300.0,
    "orca12_like": 120.0,
}
# Preset n_lon (legoESM BENCH_PRESETS): the latlon row count is DERIVED
# (Mercator placement from n_lon + lat_max), so resolution is n_lon-driven.
_BENCH_PRESET_NLON = {
    "orca1_like": 360,
    "orca025_like": 1440,
    "orca12_like": 4320,
}
# The nominal dt declared in templates/global_ocean/bench.yaml (orca1_like).
# An explicit override is detected against THIS, not the selected preset:
# switching preset must re-size dt with the grid.
_BENCH_TEMPLATE_DEFAULT_DT = _BENCH_PRESET_DT["orca1_like"]


def _bench_command(config: dict, script: str, out_dir: Path,
                   data_root: Path) -> list[str]:
    """Build the run_bench.py command from template fields (pure; testable).

    See ``_run_bench`` for the forwarding contract (preset-owned dt, steps
    not days, gates in the exit code).
    """
    grid_cfg = config.get("grid", {})
    ocean_cfg = config.get("ocean", {})
    time_cfg = config.get("time", {})
    run_cfg = config.get("run", {}) or {}

    grid_type = grid_cfg.get("type", "latlon")
    if grid_type not in ("latlon", "tripole"):
        raise ValueError(
            f"bench: grid.type={grid_type!r} is not supported "
            "(latlon | tripole — the synthetic fold lane)")

    preset = run_cfg.get("preset", "orca1_like")
    if preset not in _BENCH_PRESET_DT:
        raise ValueError(
            f"run.preset={preset!r} is not a BENCH preset "
            f"({sorted(_BENCH_PRESET_DT)})")

    cmd = [sys.executable, script, "--grid", grid_type, "--preset", preset]

    steps = run_cfg.get("steps")
    if steps is not None:
        cmd.extend(["--steps", str(steps)])
    warmup = run_cfg.get("warmup_steps")
    if warmup is not None:
        cmd.extend(["--warmup-steps", str(warmup)])

    # dt: preset-owned — forward only an explicit override (a value other
    # than the template's nominal default), so switching preset re-sizes
    # dt with the grid instead of inheriting the template's orca1_like
    # value (the baroclinic_gyre dt lesson).
    dt = time_cfg.get("dt_seconds")
    if dt is not None and float(dt) != _BENCH_TEMPLATE_DEFAULT_DT:
        cmd.extend(["--dt", str(dt)])

    # Sizing overrides: preset-owned upstream, forward only deviations.
    # grid.resolution "NxM" carries n_lon (rows are Mercator-derived, so
    # the N component is informational); forward when it differs from the
    # preset so downsized smokes are recorded in a structured field.
    res = str(grid_cfg.get("resolution", ""))
    if "x" in res:
        n_lon = int(res.split("x")[0])
        if n_lon != _BENCH_PRESET_NLON[preset]:
            cmd.extend(["--n-lon", str(n_lon)])
    nlev = grid_cfg.get("nlev")
    if nlev is not None and int(nlev) != 74:
        cmd.extend(["--nlev", str(nlev)])
    h_max = ocean_cfg.get("H_max")
    if h_max is not None and float(h_max) != 5000.0:
        cmd.extend(["--H-max", str(h_max)])
    lat_max = ocean_cfg.get("lat_max_deg")
    if lat_max is not None and float(lat_max) != 80.0:
        cmd.extend(["--lat-max", str(lat_max)])
    if grid_type == "tripole":
        n_lat = run_cfg.get("n_lat")
        if n_lat:
            cmd.extend(["--n-lat", str(n_lat)])

    if run_cfg.get("timing_jsonl"):
        cmd.extend(["--timing-jsonl",
                    str(out_dir / str(run_cfg["timing_jsonl"]))])
    if run_cfg.get("float32", False):
        cmd.append("--no-x64")

    # Verbatim passthrough: run.extra_args appended AFTER the mapped args,
    # with only the {data_root} token substituted (bench needs no data, but
    # the token keeps machine-portable cards uniform).
    for raw in (run_cfg.get("extra_args") or []):
        cmd.append(str(raw).replace("{data_root}", str(data_root)))
    return cmd


def _run_bench(config: dict, legoesm_path: Path, config_path: Path | None = None):
    """Run a BENCH performance benchmark via script delegation to
    scripts/run/run_bench.py.

    The upstream script (legoESM PR climate-federation/legoESM#1934, NEMO
    BENCH port per Irrmann et al. 2022) is the standalone timing harness:
    it builds the BenchConfig itself, so this mapping only forwards the
    knobs a template legitimately overrides — preset sizing, step count,
    timing output. Benchmarks count STEPS (NEMO ``nn_itend``), not days:
    ``time.duration_days`` is nominal and NOT forwarded. ``time.dt_seconds``
    is forwarded only when it differs from the chosen preset's measured-
    stable dt (see ``_bench_command``). Unknown knobs go via
    ``run.extra_args`` verbatim. The exit code carries the pre-registered
    stability gates (finite fields, max speed, max |eta|): a gate failure
    exits 1.

    Writes no snapshots (no I/O perturbs the measurement); the timing
    record lands in ``run.timing_jsonl`` inside the experiment directory.
    """
    import subprocess

    script = str(legoesm_path / "scripts" / "run" / "run_bench.py")
    if not Path(script).exists():
        raise FileNotFoundError(
            f"{script} not found — the BENCH lane needs legoESM's "
            f"scripts/run/run_bench.py (check the pin / legoESM checkout)")

    # The subprocess cwd becomes the legoESM repo: absolutize the timing
    # record against the experiment directory.
    out_dir = config_path.parent if config_path else Path.cwd()
    data_root = resolve_data_root()

    cmd = _bench_command(config, script, out_dir, data_root)

    run_env = {**os.environ, "JAX_ENABLE_X64": "1"}
    print(f"Running BENCH via: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=run_env, cwd=str(legoesm_path))
    if result.returncode != 0:
        raise RuntimeError(
            f"run_bench.py exited with code {result.returncode} "
            "(stability gates failed or the harness errored)")


def _run_matrix_case(config: dict, legoesm_path: Path,
                     config_path: Path | None, matrix_grid: str):
    """Run a 3D idealized case via delegation to the legoESM ocean test
    matrix (``scripts/matrix/run_ocean_test_matrix.py --only <case>``).

    The upstream matrix runner owns the scientifically-validated
    configuration of each case (grid geometry, ICs, physics, stability-
    verified dt/duration pairs — see legoESM
    ``docs/dev-notes/ocean_experiments_reference.md``). This handler maps
    the template's case + grid type onto the upstream baseline and
    forwards only the knobs a template legitimately overrides: duration,
    dt, vertical levels, resolution. Template physics fields are the
    documented intent; the upstream baseline is what runs.

    Output lands in ``<experiment-dir>/results/ocean/<case>/...``.
    """
    import subprocess

    grid_cfg = config.get("grid", {})
    time_cfg = config.get("time", {})
    ocean_cfg = config.get("ocean", {})
    case = ocean_cfg.get("case")

    script = str(legoesm_path / "scripts" / "matrix"
                 / "run_ocean_test_matrix.py")
    if not Path(script).exists():
        raise FileNotFoundError(
            f"{script} not found — the matrix-case lane needs legoESM's "
            f"scripts/matrix/run_ocean_test_matrix.py")

    # The subprocess cwd becomes the legoESM repo: absolutize the output
    # against the experiment directory (upstream writes
    # <output>/<case>/<grid>/<res>/).
    out_dir = config_path.parent if config_path else Path.cwd()
    output_arg = str(out_dir / config.get("output", {}).get(
        "path", "results/ocean"))

    cmd = [sys.executable, script,
           "--only", str(case),
           "--grid", matrix_grid,
           "--output", output_arg]

    # Overrides: only what the upstream CLI honors. duration -> --days;
    # dt/levels/resolution -> the matching flags. Absent keys keep the
    # upstream baseline (the tested configuration).
    duration_days = time_cfg.get("duration_days")
    if duration_days is not None:
        cmd.extend(["--days", str(duration_days)])
    dt = time_cfg.get("dt_seconds")
    if dt is not None:
        cmd.extend(["--dt", str(dt)])
    nlev = grid_cfg.get("nlev", grid_cfg.get("n_levels"))
    if nlev is not None:
        cmd.extend(["--levels", str(nlev)])
    resolution = grid_cfg.get("resolution")
    if resolution is not None:
        cmd.extend(["--resolution", str(resolution)])

    run_env = {**os.environ, "JAX_ENABLE_X64": "1"}
    print(f"Running {case} via ocean test matrix: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=run_env, cwd=str(legoesm_path))
    if result.returncode != 0:
        raise RuntimeError(
            f"run_ocean_test_matrix.py exited with code "
            f"{result.returncode} (case={case}, grid={matrix_grid})")


def _run_coupled(config: dict, legoesm_path: Path):
    """Run a coupled ESM experiment."""

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
    init_p.add_argument("--output-dir", type=Path, required=True, help="Write files to this directory (required)")

    tag_p = subparsers.add_parser("tag", help="Generate a tag file for a config")
    tag_p.add_argument("config", type=Path, help="Path to config.yaml")
    tag_p.add_argument("--template", default="unknown", help="Template name")

    args = parser.parse_args()

    if args.command == "run":
        run_experiment(args.config)
    elif args.command == "init":
        exp_dir = init_experiment(args.template, args.name, args.override, args.machine, args.output_dir)
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