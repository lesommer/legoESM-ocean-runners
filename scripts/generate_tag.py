#!/usr/bin/env python
"""Generate an experiment.tag file for reproducibility.

Usage:
    python scripts/generate_tag.py <config.yaml> [--template TEMPLATE_NAME]

Reads a resolved config.yaml and produces a tag file containing:
- Experiment metadata (name, mode, template)
- legoESM version info
- Grid and model parameters
- Platform info
- Config hash for reproducibility
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from runners.run_experiment import generate_tag


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate experiment.tag file")
    parser.add_argument("config", type=Path, help="Path to config.yaml")
    parser.add_argument("--template", default="unknown", help="Template name")
    parser.add_argument("--machine", default=None, help="Machine config name")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output path (default: print to stdout)")

    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    tag = generate_tag(config, args.template, args.machine)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(tag)
        print(f"Tag written to: {args.output}")
    else:
        print(tag)


if __name__ == "__main__":
    main()