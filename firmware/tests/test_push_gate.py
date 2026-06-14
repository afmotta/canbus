#!/usr/bin/env python3
"""
Standalone native test for tools/check_registry_pushed.py — the ADR-0009 open item 4
push-discipline gate. Run:  python3 firmware/tests/test_push_gate.py

Builds throwaway git repos (a work repo + a bare "remote") so the clean/pushed checks run
against real git state, no network. Covers: clean+pushed passes; uncommitted and untracked
changes under a guarded path fail (clean); no-remote and ahead-of-remote fail (pushed); a
dirty file outside the guarded paths is ignored (scope).
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_registry_pushed as gate  # noqa: E402

PATHS = ["registry"]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _new_repo(tmp: Path) -> Path:
    repo = tmp / "work"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "tester")
    (repo / "registry").mkdir()
    (repo / "registry" / "nodes.csv").write_text("node_id\n100\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


def _add_remote_and_push(repo: Path, tmp: Path) -> None:
    bare = tmp / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True,
                   capture_output=True, text=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "HEAD")


def test_clean_and_pushed_passes():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        repo = _new_repo(tmp)
        _add_remote_and_push(repo, tmp)
        assert gate.check(repo, PATHS) == []


def test_uncommitted_change_fails_clean():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        repo = _new_repo(tmp)
        _add_remote_and_push(repo, tmp)
        (repo / "registry" / "nodes.csv").write_text("node_id\n100\n101\n")
        errs = gate.check(repo, PATHS)
        assert any("uncommitted" in e.lower() for e in errs), errs


def test_untracked_file_fails_clean():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        repo = _new_repo(tmp)
        _add_remote_and_push(repo, tmp)
        (repo / "registry" / "bindings.yaml").write_text("schema_version: 1\nbindings: []\n")
        errs = gate.check(repo, PATHS)
        assert any("uncommitted" in e.lower() for e in errs), errs


def test_no_remote_fails_pushed():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(Path(d))
        errs = gate.check(repo, PATHS)
        assert any("not pushed" in e.lower() or "remote" in e.lower() for e in errs), errs


def test_ahead_of_remote_fails_pushed():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        repo = _new_repo(tmp)
        _add_remote_and_push(repo, tmp)
        # Commit again without pushing: HEAD is now ahead of the remote.
        (repo / "registry" / "nodes.csv").write_text("node_id\n100\n102\n")
        _git(repo, "commit", "-qam", "add node")
        errs = gate.check(repo, PATHS)
        assert any("not pushed" in e.lower() or "remote" in e.lower() for e in errs), errs


def test_dirty_outside_scope_passes():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        repo = _new_repo(tmp)
        _add_remote_and_push(repo, tmp)
        # A dirty file outside the guarded paths must not block a controller reflash.
        (repo / "scratch.txt").write_text("notes\n")
        assert gate.check(repo, PATHS) == []


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} push-gate tests passed.")


if __name__ == "__main__":
    main()
