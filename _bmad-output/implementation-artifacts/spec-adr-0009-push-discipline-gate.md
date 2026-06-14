# Spec: ADR-0009 push-discipline gate (open item 4)

**Date:** 2026-06-14 · **Owner:** Amelia (dev) · **Source:** ADR-0009 §6 + open item 4

## Problem

ADR-0009 §6 makes the git **remote the backup**: bindings are unrebuildable, so a registry
commit that exists only on the local machine is "an unbacked-up house." The remedy was stated
as a human rule — "push registry changes as part of the commissioning routine." Open item 4
asks for a **mechanical gate**: before reflashing the controller, verify the registry is
committed and pushed, so the rule is a checkable command instead of a discipline.

## Scope

A standalone, stdlib-only CLI: `firmware/tools/check_registry_pushed.py`.

**Guarded paths** — the ADR-0009 system of record plus the artifacts compiled into the
controller (the things whose loss/divergence breaks a controller restore):

- `registry/` — source of record (`nodes.csv`, `bindings.yaml`, `node_id_hwm`, `map.json`)
- `protocol/node_map.h`, `protocol/bindings.h` — generated, compiled into the gateway
- `gateway/ha_manifest_package.yaml` — generated HA half of the manifest handshake

Out of scope: hand-maintained firmware source (`canbus_protocol.h`, …) and node configs
(`nodes/`) — node reflashing is a separate path; the gate is about the **controller**.

## Checks (run all, report every failure, exit non-zero if any)

1. **Clean** — no uncommitted changes (staged, unstaged, or untracked) under the guarded
   paths. `git status --porcelain -- <paths>`.
2. **Pushed** — `HEAD` is contained on a remote: `git rev-list HEAD --not --remotes` is empty.
   This is the whole-commit backup guarantee (git backs up commits, not paths); if `HEAD` is
   on a remote, the guarded files in it are too. Robust to branch/upstream config — and with
   **no** remote configured it correctly fails (no remote = no backup).

The two are complementary: *clean* ensures the registry is committed; *pushed* ensures the
committed state is on the remote.

## Decisions

- **Clean is path-scoped, pushed is whole-commit.** Unrelated dirty files (docs, scratch)
  must not block a controller reflash — matches the ADR's "registry working tree is clean"
  wording — while the backup unit for "pushed" is necessarily the whole commit.
- **Freshness (registry ↔ artifacts regeneration) is a non-goal.** The §6 drift-visibility
  entities already surface a controller running a stale map at runtime. This gate is about
  *backup*, not staleness.
- **Exit codes:** `0` pass · `1` gate failed · `2` git error / not a repo. Suitable for a
  future pre-reflash script, pre-commit, or CI step.

## Tests (`firmware/tests/test_push_gate.py`, stdlib + temp git repos)

- clean + pushed → passes
- uncommitted edit under a guarded path → fails (clean)
- untracked file under a guarded path → fails (clean)
- committed but no remote → fails (pushed)
- committed, pushed, then a new commit not pushed → fails (pushed)
- a dirty file **outside** the guarded paths → still passes (scope)
