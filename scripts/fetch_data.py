#!/usr/bin/env python
"""Fetch, verify, and manage external data files for legoESM experiments.

Usage:
    python scripts/fetch_data.py fetch <template>    # Download all data for a template
    python scripts/fetch_data.py fetch-file <id>     # Download a specific file
    python scripts/fetch_data.py check <template>     # Check data availability
    python scripts/fetch_data.py list <template>      # List required data
    python scripts/fetch_data.py list-all             # List all catalog entries
    python scripts/fetch_data.py verify <id>           # Verify a downloaded file
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT_DIR / "data_catalog.yaml"
TEMPLATES_DIR = ROOT_DIR / "templates"

DEFAULT_DATA_ROOT = ROOT_DIR / "data"


def load_catalog() -> dict:
    """Load the data catalog YAML."""
    with open(CATALOG_PATH) as f:
        return yaml.safe_load(f)


def find_data_root() -> Path:
    """Find the data root directory.

    Search order:
    1. LEGOESM_DATA_DIR environment variable
    2. Machine config data_root (if machine specified)
    3. ./data (default)
    """
    env_dir = os.environ.get("LEGOESM_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return DEFAULT_DATA_ROOT


def load_template_requires(template_name: str) -> list[str]:
    """Load the requires list from a template YAML."""
    path = TEMPLATES_DIR / f"{template_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    with open(path) as f:
        config = yaml.safe_load(f)
    return config.get("requires", [])


def sha256_file(path: Path, block_size: int = 65536) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            h.update(block)
    return f"sha256:{h.hexdigest()}"


def format_size(size_mb: float) -> str:
    """Format a file size in human-readable form."""
    if size_mb < 1:
        return f"{size_mb * 1024:.0f} KB"
    elif size_mb < 1024:
        return f"{size_mb:.0f} MB"
    else:
        return f"{size_mb / 1024:.1f} GB"


def download_file(entry: dict, data_root: Path, verbose: bool = True):
    """Download a single data file from its URL."""
    url = entry.get("url")
    if not url:
        access = entry.get("access", "unknown")
        instructions = entry.get("instructions", entry.get("build_instructions", ""))
        print(f"  SKIP: Cannot auto-download (access={access})")
        if instructions:
            for line in instructions.strip().splitlines():
                print(f"       {line}")
        return False

    dest = data_root / entry["path"]
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        if verbose:
            print(f"  EXISTS: {dest}")
        return True

    if verbose:
        print(f"  DOWNLOAD: {url}")
        print(f"       -> {dest}")

    try:
        tmp_path = dest.with_suffix(dest.suffix + ".tmp")
        urllib.request.urlretrieve(url, tmp_path)
        shutil.move(str(tmp_path), str(dest))
        if verbose:
            print(f"  DONE ({format_size(entry.get('size_mb', 0))})")
        return True
    except Exception as e:
        print(f"  FAILED: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        return False


def cmd_fetch(args):
    """Download all data required by a template."""
    catalog = load_catalog()
    files = catalog["files"]
    requires = load_template_requires(args.template)
    data_root = Path(args.data_dir) if args.data_dir else find_data_root()

    if not requires:
        print(f"Template '{args.template}' requires no external data.")
        return

    print(f"Fetching data for template: {args.template}")
    print(f"Data root: {data_root}")
    print(f"Required files: {len(requires)}")
    print()

    success, failed, skipped = 0, 0, 0
    for file_id in requires:
        if file_id not in files:
            print(f"  UNKNOWN: {file_id} (not in catalog)")
            failed += 1
            continue

        entry = files[file_id]
        access = entry.get("access", "public")
        print(f"  [{file_id}] {entry.get('description', '')}")

        if access == "derived":
            build_script = entry.get("build_script", "")
            instructions = entry.get("build_instructions", "")
            print(f"  DERIVED: Must be built from other data")
            if build_script:
                print(f"  Build script: {build_script}")
            if instructions:
                for line in instructions.strip().splitlines():
                    print(f"       {line}")
            skipped += 1
            continue

        if download_file(entry, data_root, verbose=not args.quiet):
            success += 1
        else:
            if access in ("globus", "institutional"):
                skipped += 1
            else:
                failed += 1

    print(f"\nResults: {success} downloaded, {skipped} need manual setup, {failed} failed")


def cmd_fetch_file(args):
    """Download a specific file from the catalog."""
    catalog = load_catalog()
    files = catalog["files"]
    data_root = Path(args.data_dir) if args.data_dir else find_data_root()

    if args.file_id not in files:
        print(f"ERROR: '{args.file_id}' not found in catalog")
        sys.exit(1)

    entry = files[args.file_id]
    print(f"Fetching: {args.file_id}")
    print(f"  {entry.get('description', '')}")

    download_file(entry, data_root)


def cmd_check(args):
    """Check data availability for a template."""
    catalog = load_catalog()
    files = catalog["files"]
    requires = load_template_requires(args.template)
    data_root = Path(args.data_dir) if args.data_dir else find_data_root()

    if not requires:
        print(f"Template '{args.template}' requires no external data.")
        return

    print(f"Checking data for template: {args.template}")
    print(f"Data root: {data_root}")
    print()

    available, missing, need_build = 0, 0, 0
    for file_id in requires:
        if file_id not in files:
            print(f"  UNKNOWN: {file_id}")
            missing += 1
            continue

        entry = files[file_id]
        path = data_root / entry["path"]

        if entry.get("access") == "derived":
            # Check if derived path exists
            if path.exists():
                print(f"  OK (derived): {file_id} -> {path}")
                available += 1
            else:
                print(f"  MISSING (derived): {file_id} -> {path}")
                print(f"       Build: {entry.get('build_script', 'see instructions')}")
                need_build += 1
            continue

        if path.exists():
            entry_hash = entry.get("sha256", "")
            if entry_hash and entry_hash != "pending" and not args.skip_hash:
                actual_hash = sha256_file(path)
                if actual_hash == entry_hash:
                    print(f"  OK (verified): {file_id} -> {path}")
                else:
                    print(f"  HASH MISMATCH: {file_id}")
                    print(f"       expected: {entry_hash}")
                    print(f"       actual:   {actual_hash}")
                    missing += 1
                    continue
            else:
                print(f"  OK: {file_id} -> {path}")
            available += 1
        else:
            access = entry.get("access", "public")
            print(f"  MISSING ({access}): {file_id} -> {path}")
            print(f"       Size: {format_size(entry.get('size_mb', 0))}")
            if entry.get("url"):
                print(f"       URL: {entry['url']}")
            missing += 1

    print(f"\nSummary: {available} available, {missing} missing, {need_build} need building")
    if missing > 0 or need_build > 0:
        sys.exit(1)


def cmd_list(args):
    """List required data for a template."""
    catalog = load_catalog()
    files = catalog["files"]
    requires = load_template_requires(args.template)

    if not requires:
        print(f"Template '{args.template}' requires no external data.")
        return

    print(f"Data required by template: {args.template}")
    print()

    for file_id in requires:
        if file_id not in files:
            print(f"  {file_id}: NOT IN CATALOG")
            continue

        entry = files[file_id]
        access = entry.get("access", "public")
        size = format_size(entry.get("size_mb", 0))
        desc = entry.get("description", "")

        print(f"  {file_id}")
        print(f"    Description: {desc}")
        print(f"    Path: {entry['path']}")
        print(f"    Size: {size}")
        print(f"    Access: {access}")

        if args.verbose:
            if entry.get("url"):
                print(f"    URL: {entry['url']}")
            if entry.get("variables"):
                print(f"    Variables: {', '.join(entry['variables'])}")
            if entry.get("citation"):
                print(f"    Citation: {entry['citation']}")
        print()


def cmd_list_all(args):
    """List all entries in the data catalog."""
    catalog = load_catalog()
    files = catalog["files"]

    print(f"Data catalog: {len(files)} entries")
    print()

    categories = {
        "Bathymetry / Topography": [],
        "Ocean Initialization": [],
        "Ocean Grids": [],
        "Surface Forcing": [],
        "Radiation": [],
        "CMIP6 Forcing": [],
        "Topography": [],
        "Initial Conditions": [],
        "Validation": [],
    }

    for file_id, entry in files.items():
        path = entry.get("path", "")
        cat = "Other"
        if "bathymetry" in path or "topography" in path:
            cat = "Bathymetry / Topography"
        elif "woa" in path:
            cat = "Ocean Initialization"
        elif "grid" in path:
            cat = "Ocean Grids"
        elif "forcing" in path or "jra" in path:
            cat = "Surface Forcing"
        elif "rrtmgp" in path:
            cat = "Radiation"
        elif "cmip" in path:
            cat = "CMIP6 Forcing"
        elif "era" in path:
            cat = "Initial Conditions"
        elif "validation" in path:
            cat = "Validation"
        if cat in categories:
            categories[cat].append((file_id, entry))
        else:
            categories.setdefault("Other", []).append((file_id, entry))

    for cat_name, entries in categories.items():
        if not entries:
            continue
        print(f"  {cat_name}:")
        total_size = 0
        for file_id, entry in entries:
            size = entry.get("size_mb", 0)
            total_size += size
            access = entry.get("access", "public")
            print(f"    {file_id:25s} {format_size(size):>10s} {access}")
        print(f"    {'':25s} {format_size(total_size):>10s} total")
        print()


def cmd_verify(args):
    """Verify a downloaded file's checksum."""
    catalog = load_catalog()
    files = catalog["files"]
    data_root = Path(args.data_dir) if args.data_dir else find_data_root()

    if args.file_id not in files:
        print(f"ERROR: '{args.file_id}' not found in catalog")
        sys.exit(1)

    entry = files[args.file_id]
    path = data_root / entry["path"]

    if not path.exists():
        print(f"FILE NOT FOUND: {path}")
        sys.exit(1)

    if path.is_dir():
        print(f"DIRECTORY: {path}")
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        print(f"  Total size: {format_size(total / 1024 / 1024)}")
        sys.exit(0)

    actual_hash = sha256_file(path)
    expected_hash = entry.get("sha256", "pending")

    print(f"File: {path}")
    print(f"  Size: {format_size(path.stat().st_size / 1024 / 1024)}")
    print(f"  Actual hash:   {actual_hash}")

    if expected_hash == "pending":
        print(f"  Expected hash: NOT YET COMPUTED")
        print(f"  To register this hash, add to data_catalog.yaml:")
        print(f"    sha256: {actual_hash.replace('sha256:', '')}")
    elif actual_hash == expected_hash:
        print(f"  Expected hash: {expected_hash}")
        print(f"  Status: VERIFIED OK")
    else:
        print(f"  Expected hash: {expected_hash}")
        print(f"  Status: MISMATCH")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch, verify, and manage external data files for legoESM experiments"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command")

    fetch_p = subparsers.add_parser("fetch", help="Download all data for a template")
    fetch_p.add_argument("template", help="Template name (e.g. 3d_realistic/omip_jra55)")
    fetch_p.add_argument("--data-dir", default=None, help="Data root directory (default: $LEGOESM_DATA_DIR or ./data)")
    fetch_p.add_argument("-q", "--quiet", action="store_true", help="Less verbose output")

    fetch_file_p = subparsers.add_parser("fetch-file", help="Download a specific file")
    fetch_file_p.add_argument("file_id", help="File ID from data_catalog.yaml")
    fetch_file_p.add_argument("--data-dir", default=None, help="Data root directory")

    check_p = subparsers.add_parser("check", help="Check data availability for a template")
    check_p.add_argument("template", help="Template name")
    check_p.add_argument("--data-dir", default=None, help="Data root directory")
    check_p.add_argument("--skip-hash", action="store_true", help="Skip SHA-256 verification")

    list_p = subparsers.add_parser("list", help="List required data for a template")
    list_p.add_argument("template", help="Template name")
    list_p.add_argument("-v", "--verbose", action="store_true", help="Show URLs and citations")

    subparsers.add_parser("list-all", help="List all entries in the data catalog")

    verify_p = subparsers.add_parser("verify", help="Verify a downloaded file's checksum")
    verify_p.add_argument("file_id", help="File ID from data_catalog.yaml")
    verify_p.add_argument("--data-dir", default=None, help="Data root directory")

    args = parser.parse_args()

    if args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "fetch-file":
        cmd_fetch_file(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "list-all":
        cmd_list_all(args)
    elif args.command == "verify":
        cmd_verify(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()