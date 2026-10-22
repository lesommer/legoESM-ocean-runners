#!/usr/bin/env python
"""Initialize an experiment from a template.

Usage:
    python scripts/init_experiment.py <template_name> --output-dir <dir> [-o KEY=VALUE...]

Example:
    python scripts/init_experiment.py 3d_idealized/baroclinic_gyre \\
        --output-dir runs/my_gyre_run \\
        -o ocean.A_h=1e6 \\
        -o time.duration_days=730
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runners.run_experiment import init_experiment


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Initialize a legoESM experiment from a template")
    parser.add_argument("template", help="Template name (runners-owned, ocean/<stem> canonical, or legacy alias)")
    parser.add_argument("--name", help="Experiment name (default: from template)")
    parser.add_argument("-o", "--override", action="append", default=[],
                        help="Override in KEY=VALUE format (dot-notation)")
    parser.add_argument("--machine", help="Machine config name (e.g. perlmutter)")
    parser.add_argument("--output-dir", type=Path, required=True, help="Write files to this directory (required)")

    args = parser.parse_args()
    exp_dir = init_experiment(args.template, args.name, args.override, args.machine, args.output_dir)
    print(f"Experiment initialized: {exp_dir}")
    print()
    print("Files created:")
    print(f"  config.yaml       → {exp_dir / 'config.yaml'}")
    print(f"  experiment.tag    → {exp_dir / 'experiment.tag'}")
    print(f"  run.sh            → {exp_dir / 'run.sh'}")
    print()
    print("To run:")
    print(f"  cd {exp_dir}")
    print(f"  bash run.sh")


if __name__ == "__main__":
    main()