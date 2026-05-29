"""Ocean test matrix runner.

Runs cross-product test suites covering (case x grid_type x resolution)
combinations, mirroring the legoESM scripts/run_ocean_test_matrix.py API
but driven by our template YAML files.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

OCEAN_2D_TEMPLATES = [
    "2d/barotropic_gyre",
    "2d/stommel_gyre_tracer",
    "2d/inertia_gravity_wave",
]

OCEAN_3D_IDEALIZED_TEMPLATES = [
    "3d_idealized/baroclinic_gyre",
    "3d_idealized/lock_exchange",
    "3d_idealized/overflow",
    "3d_idealized/eady_instability",
    "3d_idealized/phillips_two_layer",
    "3d_idealized/acc_channel",
    "3d_idealized/dino",
    "3d_idealized/geostrophic_adjustment",
    "3d_idealized/isomip_plus",
]

OCEAN_GLOBAL_TEMPLATES = [
    "global_ocean/global_overturning",
    "global_ocean/neverworld2_lite",
    "global_ocean/omip_global",
]

ALL_OCEAN_TEMPLATES = OCEAN_2D_TEMPLATES + OCEAN_3D_IDEALIZED_TEMPLATES + OCEAN_GLOBAL_TEMPLATES


@dataclass
class TestCase:
    template: str
    name: str
    grid_type: str
    resolution: str
    nlev: int
    duration_days: int
    quick_days: int


def build_test_matrix(
    categories: list[str] | None = None,
    grid_types: list[str] | None = None,
) -> list[TestCase]:
    """Build a cross-product test matrix from templates."""
    if categories is None:
        categories = ["2d", "3d_idealized", "global_ocean"]

    templates_to_use = []
    for t in ALL_OCEAN_TEMPLATES:
        cat = t.rsplit("/", 1)[0]
        if cat in categories:
            templates_to_use.append(t)

    cases = []
    for tmpl in templates_to_use:
        path = TEMPLATES_DIR / f"{tmpl}.yaml"
        if not path.exists():
            continue
        with open(path) as f:
            cfg = yaml.safe_load(f)

        grid = cfg.get("grid", {})
        gt = grid.get("type", "latlon")
        res = str(grid.get("resolution", "unknown"))
        nlev = grid.get("n_levels", grid.get("nlev", 1))

        if grid_types and gt not in grid_types:
            continue

        quick_days = min(cfg.get("time", {}).get("duration_days", 10), 5)

        cases.append(TestCase(
            template=tmpl,
            name=cfg.get("experiment", {}).get("name", tmpl),
            grid_type=gt,
            resolution=res,
            nlev=nlev,
            duration_days=cfg.get("time", {}).get("duration_days", 10),
            quick_days=quick_days,
        ))

    return cases


def run_quick_test(case: TestCase, legoesm_path: Path, verbose: bool = False):
    """Run a quick smoke test for a single test case.

    This runs legoesm directly via Python for `quick_days` timesteps.
    """
    env = {"PYTHONPATH": f"{legoesm_path / 'src'}"}
    cmd = [
        sys.executable, "-m", "runners.run_experiment", "init",
        case.template,
        "--name", f"smoke_{case.name}",
        "-o", f"time.duration_days={case.quick_days}",
    ]
    if verbose:
        print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, env={**subprocess.os.environ, **env}, capture_output=not verbose)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="legoESM ocean test matrix runner")
    parser.add_argument(
        "--categories", nargs="+",
        default=["2d", "3d_idealized"],
        choices=["2d", "3d_idealized", "global_ocean"],
        help="Test categories to run",
    )
    parser.add_argument(
        "--grid-types", nargs="+",
        default=None,
        choices=["latlon", "cubed_sphere", "mpas", "spectral"],
        help="Grid types to test",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Run quick smoke tests (few timesteps each)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print test matrix without running",
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    cases = build_test_matrix(args.categories, args.grid_types)
    print(f"Test matrix: {len(cases)} cases")

    for i, case in enumerate(cases, 1):
        print(f"  [{i}/{len(cases)}] {case.name} ({case.grid_type}/{case.resolution}, {case.nlev} lev)")

    if args.dry_run:
        return

    from runners.run_experiment import resolve_legoesm_path
    legoesm_path = resolve_legoesm_path()

    passed, failed = 0, 0
    for case in cases:
        print(f"\nRunning: {case.name}")
        ok = run_quick_test(case, legoesm_path, args.verbose)
        if ok:
            passed += 1
            print(f"  PASS: {case.name}")
        else:
            failed += 1
            print(f"  FAIL: {case.name}")

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {len(cases)} total")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()