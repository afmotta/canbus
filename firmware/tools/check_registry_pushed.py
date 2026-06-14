#!/usr/bin/env python3
"""check_registry_pushed.py — the ADR-0009 push-discipline gate (open item 4).

Before reflashing the controller, verify the registry is committed AND pushed to the git
remote. ADR-0009 §6 makes the remote the *backup*: bindings are unrebuildable, so a registry
commit that lives only on this machine is an unbacked-up house. This turns that human rule
into a checkable command — run it as a pre-reflash gate (exit 0 = safe to flash).

Two checks (both must pass):
  1. Clean  — no uncommitted changes (staged, unstaged, or untracked) under the guarded
              paths below. Path-scoped, so unrelated dirty files don't block a reflash.
  2. Pushed — HEAD is contained on a remote (`git rev-list HEAD --not --remotes` is empty).
              Git backs up commits, not paths: if HEAD is on a remote the guarded files in
              it are too. With no remote configured this correctly fails (no remote = no
              backup). Whole-commit by nature — that is the backup unit.

Out of scope: registry<->artifact freshness (a stale compiled map is surfaced at runtime by
the §6 drift-visibility entities); hand-maintained firmware source and node configs (node
reflashing is a separate path — this gate is about the controller).

Usage:
    python tools/check_registry_pushed.py [--quiet]

Exit codes: 0 = pass · 1 = gate failed · 2 = git error / not a repo.
"""

import argparse
import subprocess
import sys
from pathlib import Path

# firmware/ — guarded paths and git invocations are relative to it.
FIRMWARE = Path(__file__).resolve().parent.parent

# ADR-0009 system of record + the artifacts compiled into the controller. registry/ covers
# nodes.csv / bindings.yaml / node_id_hwm / map.json; the headers and HA package are
# generated but get flashed, so an uncommitted one would mean flashing unbacked-up state.
GUARDED_PATHS = [
    "registry",
    "protocol/node_map.h",
    "protocol/bindings.h",
    "gateway/ha_manifest_package.yaml",
]


class GitError(Exception):
    """git was unavailable, errored, or the path is not a repository."""


def _git(repo: Path, *args: str) -> str:
    """Run a git command in `repo`, returning stdout. Raises GitError on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError as exc:  # git not installed
        raise GitError("git executable not found") from exc
    except subprocess.CalledProcessError as exc:
        raise GitError(exc.stderr.strip() or f"git {' '.join(args)} failed") from exc
    return result.stdout


def check(repo: Path, paths) -> list:
    """Return a list of human-readable failures; empty means the gate passes."""
    errors = []

    # 1. Clean: porcelain output under the guarded paths means uncommitted work.
    dirty = _git(repo, "status", "--porcelain", "--", *paths).strip()
    if dirty:
        files = ", ".join(sorted(line[3:] for line in dirty.splitlines()))
        errors.append(f"uncommitted registry changes (commit them first): {files}")

    # 2. Pushed: any commit reachable from HEAD but not from a remote is unbacked-up.
    unpushed = _git(repo, "rev-list", "HEAD", "--not", "--remotes").strip()
    if unpushed:
        n = len(unpushed.splitlines())
        errors.append(
            f"HEAD is not pushed to any remote ({n} commit(s) only local) — "
            "push before reflashing (ADR-0009 §6: the remote is the backup)"
        )

    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Gate a controller reflash on the registry being committed and pushed "
                    "(ADR-0009 §6 / open item 4).")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress the success line (errors still print)")
    args = parser.parse_args()

    try:
        errors = check(FIRMWARE, GUARDED_PATHS)
    except GitError as exc:
        print(f"✗ push gate: cannot check git state: {exc}", file=sys.stderr)
        raise SystemExit(2)

    if errors:
        print("✗ push gate FAILED — do NOT reflash the controller:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(1)

    if not args.quiet:
        print("✓ push gate: registry committed and pushed — safe to reflash the controller.")


if __name__ == "__main__":
    main()
