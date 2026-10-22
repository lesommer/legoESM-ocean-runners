#!/usr/bin/env python
"""Reproduce a past experiment from its experiment.tag file.

Usage:
    python scripts/reproduce.py path/to/experiment.tag [--run] [--verify]

What it does:
    1. Reads the experiment.tag to find runner_tag, legoESM commit, and patches
    2. Checks out the matching tag in this repo
    3. Checks out the matching legoESM commit
    4. Applies any patches listed in the tag
    5. Verifies data availability
    6. Optionally re-initializes and runs the experiment
       (re-applying the recorded overrides, so the rerun is the SAME
       experiment, not a template-default lookalike)

Options:
    --verify     Audit the tag against the CURRENT repo state and exit:
                 recompute config_hash from template+recorded overrides,
                 check every recorded patch content digest. No checkouts.
    --run        Re-initialize and run the experiment after checkout
    --data-dir   Data root directory (default: $LEGOESM_DATA_DIR or ./data)
    --legoesm-dir  Path to legoESM checkout (default: ../legoESM)
    --dry-run    Print what would be done without executing
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
# reproduce.py needs the runners package for verify (load_template /
# apply_overrides); it lives in scripts/, the package in the repo root.
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def parse_tag(tag_path: Path) -> dict:
    """Parse an experiment.tag INI file into a dict of sections."""
    config = configparser.ConfigParser()
    config.read(str(tag_path))

    result = {}
    for section in config.sections():
        result[section] = dict(config[section])
    return result


def get_current_tag() -> str | None:
    """Get the current git tag for HEAD, if any."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            capture_output=True, text=True, cwd=ROOT_DIR,
        )
        if result.returncode == 0 and result.stdout.strip().startswith("legoesm-"):
            return result.stdout.strip()
    except Exception:
        pass
    return None


def verify_tag(tag: dict) -> list[str]:
    """Audit a tag against the CURRENT repo state (no checkouts).

    Checks:
    1. config_hash — re-resolve the template + the tag's recorded overrides
       and recompute the hash (same algorithm as generate_tag). A mismatch
       means the template, the overrides, or the hash itself drifted.
    2. patch content digests — every ``patch_sha256_<stem>`` line in
       [legoESM] must match the current ``patches/<stem>.patch`` content;
       a missing file is a (distinct) problem too.

    Returns a list of problems; empty list = verified.
    """
    problems: list[str] = []
    experiment = tag.get("experiment", {})
    repro = tag.get("reproducibility", {})
    legoesm = tag.get("legoESM", {})
    template_name = experiment.get("template", "")

    if not template_name:
        return ["[experiment] template missing — cannot verify"]

    try:
        from runners.run_experiment import apply_overrides, load_template
    except ImportError as e:
        return [f"cannot import the runners package from {ROOT_DIR}: {e}"]

    try:
        cfg = load_template(template_name)
    except FileNotFoundError as e:
        return [f"template not found in this checkout (wrong tag checked out, "
                f"or template graduated/removed): {e}"]

    overrides = []
    if repro.get("overrides"):
        try:
            overrides = json.loads(repro["overrides"])
        except json.JSONDecodeError as e:
            problems.append(f"[reproducibility] overrides is not valid JSON: {e}")
    if overrides:
        cfg = apply_overrides(cfg, overrides)

    recomputed = hashlib.sha256(
        json.dumps(cfg, sort_keys=True).encode()
    ).hexdigest()[:16]
    recorded = repro.get("config_hash", "").removeprefix("sha256:")
    if recomputed != recorded:
        problems.append(
            f"config_hash mismatch: tag records {recorded or '(missing)'}, "
            f"current template+overrides resolve to {recomputed}"
        )

    for key, recorded_digest in legoesm.items():
        if not key.startswith("patch_sha256_"):
            continue
        stem = key[len("patch_sha256_"):]
        patch_file = ROOT_DIR / "patches" / f"{stem}.patch"
        if not patch_file.exists():
            problems.append(
                f"patch {stem}.patch is recorded in the tag but missing from "
                f"patches/ (merged upstream + removed here, or renamed)"
            )
            continue
        actual = hashlib.sha256(patch_file.read_bytes()).hexdigest()[:16]
        if actual != recorded_digest.removeprefix("sha256:"):
            problems.append(
                f"patch content drift: tag records {recorded_digest} for "
                f"{stem}.patch, current content hashes to sha256:{actual}"
            )

    return problems


def checkout_tag(runner_tag: str, dry_run: bool = False) -> bool:
    """Checkout a git tag (or untagged@<sha> fallback) in this repository."""
    # The untagged-window fallback (run_experiment._get_current_tag):
    # "untagged@<sha>" reproduces from the recorded commit; a bare
    # "untagged" carries no resolvable identity and fails here.
    ref = runner_tag
    if ref.startswith("untagged@"):
        ref = ref.split("@", 1)[1]
        print(f"  NOTE: {runner_tag} records an untagged commit; checking out {ref}")
    cmd = ["git", "checkout", ref]
    if dry_run:
        print(f"  Would run: {' '.join(cmd)} (in {ROOT_DIR})")
        return True

    result = subprocess.run(cmd, cwd=ROOT_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: Failed to checkout tag {runner_tag}")
        print(f"  {result.stderr.strip()}")
        return False
    print(f"  Checked out tag: {runner_tag}")
    return True


def checkout_legoesm(commit: str, legoesm_dir: Path, dry_run: bool = False) -> bool:
    """Checkout a specific commit in the legoESM repo."""
    if not legoesm_dir.is_dir():
        print(f"  ERROR: legoESM not found at {legoesm_dir}")
        print(f"         Set LEGOESM_DIR environment variable or use --legoesm-dir")
        return False

    cmd = ["git", "checkout", commit]
    if dry_run:
        print(f"  Would run: {' '.join(cmd)} (in {legoesm_dir})")
        return True

    result = subprocess.run(cmd, cwd=legoesm_dir, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: Failed to checkout legoESM commit {commit}")
        print(f"  {result.stderr.strip()}")
        return False
    print(f"  Checked out legoESM commit: {commit[:12]}")
    return True


def apply_patches(patches_str: str, dry_run: bool = False) -> bool:
    """Apply patches listed in the tag file."""
    patches = [p.strip() for p in patches_str.split(",") if p.strip()]
    if not patches:
        print("  No patches to apply.")
        return True

    script = ROOT_DIR / "scripts" / "apply_patches.sh"
    if not script.exists():
        print(f"  ERROR: Patch script not found: {script}")
        return False

    for patch_name in patches:
        patch_path = ROOT_DIR / "patches" / patch_name
        if not patch_path.exists():
            print(f"  WARNING: Patch not found: {patch_path}")
            print(f"           It may have been merged into legoESM main since this experiment.")
            continue

        if dry_run:
            print(f"  Would apply patch: {patch_name}")
            continue

        # Idempotency: if the legoESM worktree already carries this patch
        # (git apply --check fails but --reverse --check succeeds), skip it
        # instead of erroring — reproducing on a prepared checkout works.
        legoesm_dir = os.environ.get("LEGOESM_DIR", str(ROOT_DIR.parent / "legoESM"))
        probe = subprocess.run(
            ["git", "-C", legoesm_dir, "apply", "--check", str(patch_path)],
            capture_output=True, text=True,
        )
        if probe.returncode != 0:
            reverse = subprocess.run(
                ["git", "-C", legoesm_dir, "apply", "--reverse", "--check", str(patch_path)],
                capture_output=True, text=True,
            )
            if reverse.returncode == 0:
                print(f"  Already applied: {patch_name} (skipping)")
                continue

        cmd = ["bash", str(script), patch_name]
        result = subprocess.run(cmd, cwd=ROOT_DIR, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR: Failed to apply patch {patch_name}")
            print(f"  {result.stderr.strip()}")
            return False
        print(f"  Applied patch: {patch_name}")

    return True


def check_data_availability(template_name: str, data_dir: Path, dry_run: bool = False) -> bool:
    """Check data availability for a template."""
    script = ROOT_DIR / "scripts" / "fetch_data.py"
    if not script.exists():
        print(f"  WARNING: fetch_data.py not found, skipping data check")
        return True

    cmd = [sys.executable, str(script), "check", template_name, "--data-dir", str(data_dir)]
    if dry_run:
        print(f"  Would run: {' '.join(cmd)}")
        return True

    result = subprocess.run(cmd, cwd=ROOT_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  WARNING: Some data files are missing")
        print(f"  {result.stdout}")
        print(f"  Run: python scripts/fetch_data.py fetch {template_name} --data-dir {data_dir}")
        return False
    print(f"  All required data is available.")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Reproduce a past experiment from its experiment.tag file"
    )
    parser.add_argument("tag_file", type=Path, help="Path to experiment.tag file")
    parser.add_argument("--verify", action="store_true",
                        help="Audit the tag against the current repo state "
                             "(config_hash recompute + patch digests) and exit")
    parser.add_argument("--run", action="store_true",
                        help="Re-initialize and run the experiment after checkout")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Directory for the re-initialized experiment "
                             "(default: ./reproduced_<name>; required by init)")
    parser.add_argument("--data-dir", default=None,
                        help="Data root directory (default: $LEGOESM_DATA_DIR or ./data)")
    parser.add_argument("--legoesm-dir", default=None,
                        help="Path to legoESM checkout (default: ../legoESM)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be done without executing")

    args = parser.parse_args()

    if not args.tag_file.exists():
        print(f"ERROR: Tag file not found: {args.tag_file}")
        sys.exit(1)

    # Parse the tag file
    try:
        tag = parse_tag(args.tag_file)
    except configparser.Error as e:
        print(f"ERROR: {args.tag_file} is not a valid experiment.tag (INI format): {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Reproducing experiment from: {args.tag_file}")

    experiment = tag.get("experiment", {})
    legoesm = tag.get("legoESM", {})
    repro = tag.get("reproducibility", {})
    data_section = tag.get("data", {})

    print(f"  Name:    {experiment.get('name', 'unknown')}")
    print(f"  Template: {experiment.get('template', 'unknown')}")
    print(f"  Mode:    {experiment.get('mode', 'unknown')}")
    print()

    # Verify mode: audit against the CURRENT state, then exit (no checkouts).
    if args.verify:
        print("[verify] Auditing tag against the current repo state...")
        problems = verify_tag(tag)
        if problems:
            print(f"\n{len(problems)} problem(s):")
            for p in problems:
                print(f"  - {p}")
            print("\nNOT verified: the tag does not match this checkout "
                  "(template/overrides or patch chain drifted,")
            print("or the tag belongs to a different runner tag — check it out first).")
            sys.exit(1)
        print("Verified: config_hash reproduces from template + recorded overrides;")
        print("all recorded patch digests match the current patches/ chain.")
        sys.exit(0)

    # Step 1: Checkout the runner tag
    runner_tag = repro.get("runner_tag") or repro.get("legoesm_ref", "unknown")
    if runner_tag and runner_tag != "unknown":
        print(f"[1/4] Checking out runner tag: {runner_tag}")
        if not checkout_tag(runner_tag, dry_run=args.dry_run):
            print("  Hint: Available tags:")
            if not args.dry_run:
                subprocess.run(["git", "tag", "-l", "legoesm-*"], cwd=ROOT_DIR)
            sys.exit(1)
    else:
        print("[1/4] No runner_tag found, staying on current version")
        current = get_current_tag()
        if current:
            print(f"  Currently on: {current}")
        else:
            print(f"  WARNING: No tag on current HEAD. Reproducibility is not guaranteed.")

    # Step 2: Checkout legoESM commit
    commit = legoesm.get("commit", "")
    if commit:
        legoesm_dir = Path(args.legoesm_dir) if args.legoesm_dir else (
            Path(os.environ.get("LEGOESM_DIR", str(ROOT_DIR.parent / "legoESM")))
        )
        print(f"\n[2/4] Checking out legoESM commit: {commit[:12]}")
        if not checkout_legoesm(commit, legoesm_dir, dry_run=args.dry_run):
            sys.exit(1)
    else:
        print("\n[2/4] No legoESM commit specified in tag file")

    # Step 3: Apply patches
    patches = legoesm.get("patches", "")
    print(f"\n[3/4] Applying patches: {patches or 'none'}")
    if not apply_patches(patches, dry_run=args.dry_run):
        sys.exit(1)

    # Step 4: Check data availability
    template_name = experiment.get("template", "")
    data_dir = Path(args.data_dir) if args.data_dir else (
        Path(os.environ.get("LEGOESM_DATA_DIR", str(ROOT_DIR / "data")))
    )
    print(f"\n[4/4] Checking data availability (template: {template_name})")
    if template_name:
        check_data_availability(template_name, data_dir, dry_run=args.dry_run)
    else:
        print("  No template specified in tag file, skipping data check.")

    # Summary
    print("\n" + "=" * 60)
    print("Reproduction environment ready.")
    if args.run and template_name:
        exp_name = experiment.get("name", "reproduced")
        print(f"\nRe-initializing experiment: {exp_name}")
        out_dir = args.output_dir if args.output_dir is not None else (
            ROOT_DIR / f"reproduced_{exp_name}")
        cmd = [
            sys.executable,
            str(ROOT_DIR / "scripts" / "init_experiment.py"),
            template_name,
            "--name", f"{exp_name}_reproduced",
            "--output-dir", str(out_dir),
        ]
        # Re-apply the recorded overrides: without this, a reproduced run
        # silently uses template defaults (the 2026-10-21 audit finding).
        overrides_json = repro.get("overrides")
        if overrides_json:
            try:
                for ov in json.loads(overrides_json):
                    cmd += ["-o", str(ov)]
            except json.JSONDecodeError:
                print("  WARNING: tag [reproducibility] overrides is not valid JSON;")
                print("           re-initializing with TEMPLATE DEFAULTS (not the recorded experiment).")
                print(f"           (raw: {overrides_json!r})")
        if args.dry_run:
            print(f"  Would init: {' '.join(cmd)}")
        else:
            subprocess.run(cmd, cwd=ROOT_DIR)
    else:
        print("\nTo initialize and run the experiment:")
        if template_name:
            print(f"  python scripts/init_experiment.py {template_name} --name reproduced_run --output-dir runs/reproduced_run")
            print(f"  cd runs/reproduced_run && bash run.sh")
        else:
            print("  (No template name found in tag file)")

    print("\nWhen done, return to the latest version:")
    print("  git checkout main")
    print(f"  cd ../legoESM && git checkout main")


if __name__ == "__main__":
    main()