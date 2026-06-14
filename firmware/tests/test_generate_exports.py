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
import subprocess
import sys
import tempfile
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


def test_node_map_emits_version_constant():
    # node_map.h carries NODE_MAP_VERSION so the gateway can expose its compiled map
    # identity as a drift-visibility diagnostic (ADR-0009 §6), without breaking the
    # frozen-additive struct/accessor contract.
    entries = [(101, 8, 0, "Living room"), (100, 7, 0, 'Hall "A"')]
    version = "0123456789abcdef"
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "node_map.h"
        g.write_node_map(entries, version, path)
        h = path.read_text()
    assert f'NODE_MAP_VERSION[] = "{version}";' in h
    # The existing contract is intact: struct, sentinel, accessors, sorted rows, escaping.
    assert "struct NodeMapEntry" in h
    assert "NODE_MAP_UNKNOWN = 0xFF" in h
    assert "node_map_name(" in h
    assert h.index('{100, 7, 0, "Hall \\"A\\""},') < h.index('{101, 8, 0, "Living room"},')


def test_generator_node_map_version_matches_map_json():
    # ADR-0009 §6 drift correlation: the gateway-compiled NODE_MAP_VERSION must equal the
    # map_version published in registry/map.json, or a dashboard comparison is meaningless.
    # The generator is byte-stable (unchanged input regenerates no diff), so running it in
    # place leaves the working tree clean.
    firmware = Path(__file__).resolve().parent.parent
    subprocess.run(
        [sys.executable, "tools/generate_nodes.py"],
        cwd=firmware, check=True, capture_output=True, text=True,
    )
    map_version = json.loads((firmware / "registry" / "map.json").read_text())["map_version"]
    header = (firmware / "protocol" / "node_map.h").read_text()
    assert f'NODE_MAP_VERSION[] = "{map_version}";' in header


def test_generator_aborts_before_writing_node_files():
    # validate-before-persist: an invalid bindings.yaml must abort the generator before any
    # node artifact (nodes/*.yaml, node_map.h) is written, so a bad manifest can't leave the
    # tree half-regenerated. Driven against a temp ROOT so the real registry is untouched.
    saved_root = g.ROOT
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for sub in ("registry", "protocol", "gateway"):
            (root / sub).mkdir()
        (root / "registry" / "nodes.csv").write_text(
            "node_id,floor,room,board,location,sensors\n100,0,7,0,Hall,0\n"
        )
        # node_id 999 is not in nodes.csv -> manifest invalid -> generator aborts.
        (root / "registry" / "bindings.yaml").write_text(
            "schema_version: 1\nbindings:\n"
            "  - node_id: 999\n    button: 0\n    event: single\n    relay: 0\n    op: toggle\n"
        )
        g.ROOT = root
        try:
            try:
                g.main()
                raise AssertionError("expected SystemExit on an invalid manifest")
            except SystemExit as e:
                assert e.code == 1
            assert list((root / "nodes").glob("*.yaml")) == [], "node configs written before abort"
            assert not (root / "protocol" / "node_map.h").exists(), "node_map.h written before abort"
        finally:
            g.ROOT = saved_root


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
