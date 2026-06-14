#!/usr/bin/env python3
"""
bindings.py — Binding manifest (registry/bindings.yaml) reader, validator, and the
canonical manifest hash (ADR-0009 §2/§3).

The binding manifest is ADR-0003's fallback behavior as data: a list of bindings keyed
`(node_id, button, event)` mapping to a controller-side action (relay channel + op). It is
the second meaning-bearing artifact after `nodes.csv`, and its hash is the `manifest_hash`
the gateway and Home Assistant must agree on for `ha_ready` (ADR-0003). The generator
stamps this hash into both sides in one run, so agreement is by construction and drift is
detectable (a mismatch keeps `ha_ready` off).

Why a hand-rolled reader (no PyYAML): `generate_nodes.py` is stdlib-only by project rule,
but ADR-0009 §2 mandates YAML for the manifest (human-edited, git-diff reviewed). So this
module ships a small reader for a STRICT SUBSET of YAML and nothing more:

  schema_version: 1
  bindings:
    - node_id: 100
      button: 0
      event: single
      relay: 0
      op: toggle

Subset rules (a file outside them is an error, never a silent misread):
  - Two top-level keys only: `schema_version` (int) and `bindings`.
  - `bindings:` is either `[]` (empty) or a block list of flat mappings.
  - Each binding is scalar-valued only — no nesting, anchors, flow style, or multi-line.
  - `#` starts a comment at line start or after whitespace; scalars never contain `#`.

If a future binding shape needs structure this subset cannot express, that is the
Ask-First decision to adopt PyYAML rather than grow this reader (ADR-0009 open item 1).
"""

import csv
import hashlib
import json
import re
from pathlib import Path

SCHEMA_VERSION = 1
REQUIRED_KEYS = ("node_id", "button", "event", "relay", "op")
# Buttons are the gesture index into the standard 8-button set (0-7, packages/base_node.yaml).
BUTTON_MAX = 7
# Minimal action vocabulary (ADR-0009 open item 1 — grows additively once the controller
# board / relay channels are chosen, ADR-0003 open item 7).
VALID_OPS = ("on", "off", "toggle")


class BindingError(Exception):
    """Raised for any manifest the strict subset reader/validator rejects."""


def _strip_comment(line: str) -> str:
    # YAML comments start with '#' at line start or after whitespace. The subset forbids
    # '#' inside scalars, so splitting on (start|whitespace)+'#' cannot eat a real value.
    m = re.search(r"(^|\s)#", line)
    return line[: m.start()] if m else line


def _scalar(token: str):
    """An int if the token is a plain integer, else the unquoted string."""
    tok = token.strip()
    if len(tok) >= 2 and tok[0] in "\"'" and tok[-1] == tok[0]:
        return tok[1:-1]
    if re.fullmatch(r"-?\d+", tok):
        return int(tok)
    return tok


def _split_kv(stripped: str, lineno: int):
    if ":" not in stripped:
        raise BindingError(f"line {lineno}: expected 'key: value', got {stripped!r}")
    key, _, val = stripped.partition(":")
    return key.strip(), _scalar(val)


def load_bindings(path: Path) -> dict:
    """Parse the strict-subset manifest into {'schema_version': int, 'bindings': [ {...} ]}."""
    schema_version = None
    bindings: list[dict] = []
    current: dict | None = None
    in_bindings = False

    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0:
            if current is not None:
                bindings.append(current)
                current = None
            in_bindings = False
            key, val = _split_kv(stripped, lineno)
            if key == "schema_version":
                schema_version = val
            elif key == "bindings":
                in_bindings = True
                if val not in ("", "[]"):
                    raise BindingError(
                        f"line {lineno}: inline 'bindings' must be empty ('[]') or a block list"
                    )
            else:
                raise BindingError(f"line {lineno}: unknown top-level key {key!r}")
            continue

        # Indented line — only valid inside the bindings block.
        if not in_bindings:
            raise BindingError(f"line {lineno}: unexpected indented content {stripped!r}")
        if stripped.startswith("- "):
            if current is not None:
                bindings.append(current)
            current = {}
            key, val = _split_kv(stripped[2:].strip(), lineno)
            current[key] = val
        else:
            if current is None:
                raise BindingError(f"line {lineno}: mapping line outside a '- ' list item")
            key, val = _split_kv(stripped, lineno)
            current[key] = val

    if current is not None:
        bindings.append(current)
    return {"schema_version": schema_version, "bindings": bindings}


def read_node_ids(csv_path: Path) -> set:
    """Collect the valid node_id set from the registry CSV (validation source)."""
    with open(csv_path, newline="") as f:
        return {int(row["node_id"]) for row in csv.DictReader(f)}


def validate(parsed: dict, valid_node_ids: set) -> list:
    """Return a list of human-readable errors; empty means the manifest is valid."""
    errors = []
    if parsed.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {SCHEMA_VERSION}, got {parsed.get('schema_version')!r}"
        )

    seen = set()
    for i, b in enumerate(parsed.get("bindings") or []):
        where = f"binding {i}"
        missing = [k for k in REQUIRED_KEYS if k not in b]
        if missing:
            errors.append(f"{where}: missing key(s) {', '.join(missing)}")
            continue
        for k in ("node_id", "button", "relay"):
            if not isinstance(b[k], int):
                errors.append(f"{where}: '{k}' must be an integer, got {b[k]!r}")
        # A button outside the standard 8-button set (0-7) is a silently dead binding —
        # no such gesture is ever emitted. Guard only when button parsed as an int.
        if isinstance(b["button"], int) and not (0 <= b["button"] <= BUTTON_MAX):
            errors.append(f"{where}: button {b['button']} out of range (valid: 0-{BUTTON_MAX})")
        if b["node_id"] not in valid_node_ids:
            errors.append(f"{where}: node_id {b['node_id']} is not in the registry (nodes.csv)")
        if b["op"] not in VALID_OPS:
            errors.append(f"{where}: op {b['op']!r} not in {VALID_OPS}")
        key = (b["node_id"], b["button"], b["event"])
        if key in seen:
            errors.append(f"{where}: duplicate (node_id, button, event) key {key}")
        seen.add(key)
    return errors


def canonical_hash(parsed: dict) -> str:
    """SHA-256 over the canonical manifest structure, truncated to 16 hex chars.

    Canonical = bindings sorted by (node_id, button, event) with object keys sorted, dumped
    with no incidental whitespace. So reordering bindings, reordering keys, reflowing
    whitespace, or editing comments cannot change the hash — only the data can (ADR-0009 §3).
    """
    sorted_bindings = sorted(
        parsed.get("bindings") or [],
        key=lambda b: (b["node_id"], b["button"], str(b["event"])),
    )
    canonical = {"schema_version": parsed.get("schema_version"), "bindings": sorted_bindings}
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
