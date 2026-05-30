"""Coupled ESM runner.

Handles coupled atmosphere-ocean experiments using CoupledConfig presets.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

COUPLED_PRESETS = {
    "aquaplanet": "coupled_aquaplanet",
    "slab": "coupled_slab",
    "full": "coupled_full",
}


def list_coupled_templates() -> list[str]:
    """Return available coupled experiment template names."""
    coupled_dir = TEMPLATES_DIR / "coupled"
    templates = []
    for yaml_file in sorted(coupled_dir.glob("coupled_*.yaml")):
        templates.append(f"coupled/{yaml_file.stem}")
    return templates


def main():
    parser = argparse.ArgumentParser(description="Run coupled legoESM experiments")
    subparsers = parser.add_subparsers(dest="command")

    list_p = subparsers.add_parser("list", help="List coupled templates")
    run_p = subparsers.add_parser("run", help="Run a coupled experiment")
    run_p.add_argument("preset", choices=list(COUPLED_PRESETS.keys()), help="Coupled preset")
    run_p.add_argument("--resolution", type=int, default=48, help="Grid resolution")
    run_p.add_argument("--days", type=int, default=365, help="Simulation days")
    run_p.add_argument("--machine", default=None, help="Machine config")

    args = parser.parse_args()

    if args.command == "list":
        for t in list_coupled_templates():
            print(t)
    elif args.command == "run":
        template_name = f"coupled/{COUPLED_PRESETS[args.preset]}"
        from runners.run_experiment import init_experiment
        overrides = [
            f"grid.resolution={args.resolution}",
            f"time.duration_days={args.days}",
        ]
        exp_dir = init_experiment(template_name, overrides=overrides, machine=args.machine)
        print(f"Coupled experiment initialized: {exp_dir}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()