#!/usr/bin/env python3
"""
Standalone native test for the ADR-0009 §4/§7 export pipeline in tools/generate_nodes.py
(no ESPHome required). Run:  python3 firmware/tests/test_generate_exports.py

Covers the pure renderers added for the export slice:
  - build_map_export: field shape, node-order independence, deterministic map_version that
    is sensitive to node and binding-hash changes (the "no wall-clock" stamp decision).
  - render_bindings_header: empty manifest -> null table + size 0; populated -> sorted
    BINDINGS[] rows; the hash and binding_find accessor are always present.
  - render_ha_package: the manifest hash is baked into the generated heartbeat.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import generate_nodes as g  # noqa: E402

NODES = [
    {"node_id": 101, "floor": 0, "room": 8, "board": 0, "location": "Living room", "sensors": 0},
    {"node_id": 100, "floor": 0, "room": 7, "board": 0, "location": "Hallway", "sensors": 1},
]
HASH = "d66767448ba37b2f"


def test_map_export_shape_and_node_sort():
    m = g.build_map_export(NODES, HASH)
    assert m["schema_version"] == 1
    assert m["manifest_hash"] == HASH
    assert len(m["map_version"]) == 16
    # Nodes are sorted by node_id regardless of input order, and carry the full §7 field set.
    assert [n["node_id"] for n in m["nodes"]] == [100, 101]
    assert m["nodes"][0] == {
        "node_id": 100, "floor": 0, "room": 7, "board": 0,
        "location": "Hallway", "sensors": 1,
    }
    # Serializable as the committed map.json.
    json.dumps(m)


def test_map_version_order_invariant():
    # Reordering the CSV rows must not change the export's identity.
    a = g.build_map_export(NODES, HASH)
    b = g.build_map_export(list(reversed(NODES)), HASH)
    assert a == b
    assert a["map_version"] == b["map_version"]


def test_map_version_sensitive_to_nodes_and_hash():
    base = g.build_map_export(NODES, HASH)
    moved = [dict(n) for n in NODES]
    moved[0]["room"] = 99
    assert g.build_map_export(moved, HASH)["map_version"] != base["map_version"]
    # A binding-only change (new manifest hash) also rolls the map version.
    assert g.build_map_export(NODES, "ffffffffffffffff")["map_version"] != base["map_version"]


def test_bindings_header_empty():
    h = g.render_bindings_header(HASH, [])
    assert f'BINDINGS_MANIFEST_HASH[] = "{HASH}"' in h
    assert "const BindingEntry *BINDINGS = nullptr;" in h
    assert "BINDINGS_SIZE = 0;" in h
    assert "binding_find(" in h


def test_bindings_header_populated_and_sorted():
    rows = [
        {"node_id": 101, "button": 3, "event": "double", "relay": 2, "op": "on"},
        {"node_id": 100, "button": 0, "event": "single", "relay": 0, "op": "toggle"},
    ]
    h = g.render_bindings_header(HASH, rows)
    assert "inline constexpr BindingEntry BINDINGS[] = {" in h
    assert "sizeof(BINDINGS)" in h
    # Sorted by (node_id, button, event): node 100 row precedes node 101.
    i100 = h.index('{100, 0, "single", 0, "toggle"}')
    i101 = h.index('{101, 3, "double", 2, "on"}')
    assert i100 < i101


def test_ha_package_bakes_hash():
    p = g.render_ha_package(HASH)
    assert f'manifest_hash: "{HASH}"' in p
    assert "esphome.canbus_gateway_ha_readiness_heartbeat" in p
    assert "GENERATED" in p


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} export-pipeline tests passed.")


if __name__ == "__main__":
    main()
