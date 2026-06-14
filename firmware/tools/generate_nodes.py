#!/usr/bin/env python3
"""
generate_nodes.py — Generate ESPHome node configs from the registry CSV.

Usage:
    1. Fill in registry/nodes.csv with your physical layout
    2. Run: python tools/generate_nodes.py
    3. Generated configs appear in nodes/

CSV format:
    node_id,floor,room,board,location,sensors
    100,0,7,0,"Ground floor hallway",0

The optional `sensors` column (blank/0 = none, 1 = SHT45+SEN66 kit) adds the ADR-0006
sensor_kit package to the generated node. Sensor frames carry the host node's node_id,
so a sensor-equipped node's registry room must be the sensors' physical room.

Flat node_id model (ADR-0007): node_id is the node's only identity, carried in the 29-bit
Extended CAN ID. It is the ONLY thing flashed into the node. floor/room/board/location are
map-seed metadata for the central node_id -> {...} map on the controller/HA — they are NOT
flashed into the node config (kept here as the registry / map seed).

Every node carries the standard 8-button set (btn0–btn7), SPI/CAN pins, and heartbeat from
packages/base_node.yaml, so each generated file is minimal: just its node_id + debounce_ms
and a single include.
"""

import csv
import hashlib
import json
import sys
from pathlib import Path

import bindings  # binding-manifest reader + canonical hash (ADR-0009)

ROOT = Path(__file__).resolve().parent.parent  # firmware/

TEMPLATE = """\
# =============================================================================
# Node: {name} — node_id {node_id}
# =============================================================================
# GENERATED from registry/nodes.csv by tools/generate_nodes.py. DO NOT EDIT.
# Identity-only: the node knows just its node_id. Floor/room/board/location are NOT known at
# flash time (the node is flashed at allocation, positioned/commissioned later) — they live in
# the registry and the gateway's node_map.h, never here (ADR-0007).
# Buttons:  standard 8-button set (btn0–btn7) from packages/base_node.yaml
{sensor_comment}# CAN IDs (29-bit Extended, computed at runtime from node_id):
#   Input  = 0x{input_id:08X}  (CAT_INPUT,  node -> controller, button events)
#   Status = 0x{status_id:08X}  (CAT_STATUS, node -> controller, heartbeat)
# =============================================================================

substitutions:
  node_id: "{node_id}"
  debounce_ms: "50"

packages:
  base: !include ../packages/base_node.yaml
{sensor_pkg}"""

# Appended to TEMPLATE for rows with sensors=1 (ADR-0006). The sensor frames carry the host
# node's node_id, so the host's registry room must be the sensors' physical room.
SENSOR_COMMENT = (
    "# Sensors:  SHT45 + SEN66 kit from packages/sensor_kit.yaml "
    "(CAT_SENSOR, host room = sensor room)\n"
)
SENSOR_PKG = "  sensor_kit: !include ../packages/sensor_kit.yaml\n"

FLOOR_LABELS = {0: "Ground", 1: "First", 2: "Second", 3: "Third"}
EXAMPLE_ROWS = [
    ["node_id", "floor", "room", "board", "location", "sensors"],
    [100, 0, 7, 0, "Ground floor hallway", 0],
    [101, 0, 8, 0, "Ground floor living room", 0],
]

# CAN ID layout — must match canbus_protocol.h: [category:4][node_id:13][reserved:12].
CAT_SHIFT = 25
NODE_SHIFT = 12
CAT_INPUT, CAT_STATUS = 1, 3
NODE_ID_MAX = 8191  # 13 bits
ROOM_BOARD_MAX = 255  # room/board are uint8 in node_map.h (matches commission.py MAX_RB)


def can_id(category: int, node_id: int) -> int:
    return ((category & 0x0F) << CAT_SHIFT) | ((node_id & 0x1FFF) << NODE_SHIFT)


def _c_str(s: str) -> str:
    """Escape a Python string for a C string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def write_node_map(entries, map_version: str, path: Path) -> None:
    """Emit the gateway's compiled central map: node_id -> {room, board, name} (ADR-0007).

    NODE_MAP_VERSION is the same deterministic map_version stamped into registry/map.json
    (build_map_export); compiling it in lets the gateway expose its map identity as a
    drift-visibility diagnostic (ADR-0009 §6) that a dashboard compares against the committed
    map.json — surfacing "committed in git but not yet reflashed" instead of a misbehaving
    button. It tracks the full registry map (incl. floor/sensors), not just the compiled rows,
    so the comparison is against map.json verbatim; over-signalling (a floor-only edit rolls
    the version) errs toward a harmless reflash, the safe direction."""
    rows = "\n".join(
        f'    {{{nid}, {room}, {board}, "{_c_str(loc)}"}},'
        for nid, room, board, loc in sorted(entries)
    )
    path.write_text(
        "#pragma once\n"
        "#include <cstdint>\n"
        "#include <cstddef>\n\n"
        "// =============================================================================\n"
        "// node_map.h — GENERATED from nodes.csv by generate_nodes.py. DO NOT EDIT.\n"
        "// Central node_id -> {room, board, name} map (ADR-0007), compiled into the gateway.\n"
        "// An unknown node_id resolves to the sentinel (room/board 0xFF, name \"unknown\") —\n"
        "// i.e. a node that is on the bus but not yet in the map (uncommissioned).\n"
        "// NODE_MAP_VERSION mirrors registry/map.json's map_version for drift visibility (§6).\n"
        "// =============================================================================\n\n"
        f'inline constexpr char NODE_MAP_VERSION[] = "{map_version}";\n\n'
        "struct NodeMapEntry { uint16_t node_id; uint8_t room; uint8_t board; const char *name; };\n\n"
        "inline constexpr uint8_t NODE_MAP_UNKNOWN = 0xFF;\n\n"
        f"inline constexpr NodeMapEntry NODE_MAP[] = {{\n{rows}\n}};\n"
        "inline constexpr std::size_t NODE_MAP_SIZE = sizeof(NODE_MAP) / sizeof(NODE_MAP[0]);\n\n"
        "inline const NodeMapEntry *node_map_find(uint16_t node_id) {\n"
        "  for (std::size_t i = 0; i < NODE_MAP_SIZE; i++)\n"
        "    if (NODE_MAP[i].node_id == node_id) return &NODE_MAP[i];\n"
        "  return nullptr;\n"
        "}\n"
        "inline bool node_map_known(uint16_t node_id) { return node_map_find(node_id) != nullptr; }\n"
        "inline uint8_t node_map_room(uint16_t node_id) { auto e = node_map_find(node_id); return e ? e->room : NODE_MAP_UNKNOWN; }\n"
        "inline uint8_t node_map_board(uint16_t node_id) { auto e = node_map_find(node_id); return e ? e->board : NODE_MAP_UNKNOWN; }\n"
        "inline const char *node_map_name(uint16_t node_id) { auto e = node_map_find(node_id); return e ? e->name : \"unknown\"; }\n"
    )


def _digest(payload) -> str:
    """Deterministic 16-hex content marker over a JSON-able payload (same family as the
    binding canonical hash). Used as the map's version stamp instead of a wall-clock
    timestamp, so an unchanged export regenerates byte-for-byte (Alberto's call, ADR-0009 §7:
    the 'generation marker' is content identity, not time — no diff churn on every run)."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def render_bindings_header(manifest_hash: str, bindings_list) -> str:
    """Render protocol/bindings.h: the binding-manifest identity (ADR-0009 §3) PLUS the full
    compiled BINDINGS[] fallback table (ADR-0009 §4). Frozen-additive, mirrors node_map.h.

    Deterministic — no generation timestamp — so regenerating unchanged bindings produces no
    diff. The table is the controller's fallback-bindings artifact; it is committed now and
    grows as bindings.yaml is authored (today it is empty: fallback is still log-only,
    ADR-0003 open item 7). event/op are stored as C strings (like node_map.h names) — no new
    enums — so the action vocabulary can grow additively without a header redesign.
    """
    ordered = sorted(bindings_list, key=lambda b: (b["node_id"], b["button"], str(b["event"])))
    if ordered:
        rows = "\n".join(
            f'    {{{b["node_id"]}, {b["button"]}, "{_c_str(str(b["event"]))}", '
            f'{b["relay"]}, "{_c_str(str(b["op"]))}"}},'
            for b in ordered
        )
        table = (
            f"inline constexpr BindingEntry BINDINGS[] = {{\n{rows}\n}};\n"
            "inline constexpr std::size_t BINDINGS_SIZE = sizeof(BINDINGS) / sizeof(BINDINGS[0]);\n"
        )
    else:
        # An empty manifest yields a 0-length table. A zero-size array is non-standard, so
        # expose a null pointer + size 0 instead — binding_find() never dereferences it.
        table = (
            "inline constexpr const BindingEntry *BINDINGS = nullptr;\n"
            "inline constexpr std::size_t BINDINGS_SIZE = 0;\n"
        )
    return (
        "#pragma once\n"
        "#include <cstdint>\n"
        "#include <cstddef>\n"
        "#include <cstring>\n\n"
        "// =============================================================================\n"
        "// bindings.h — GENERATED from registry/bindings.yaml by tools/generate_nodes.py. DO NOT EDIT.\n"
        "// Binding-manifest identity + compiled fallback table for the ha_ready arbitration\n"
        "// (ADR-0009 §3/§4). BINDINGS_MANIFEST_HASH is the canonical hash of bindings.yaml,\n"
        "// which the gateway compares against the hash Home Assistant echoes in its readiness\n"
        "// heartbeat (ADR-0003); a mismatch keeps ha_ready off. BINDINGS[] is the controller's\n"
        "// fallback action table — frozen-additive, currently log-only (ADR-0003 open item 7).\n"
        "// =============================================================================\n\n"
        f'inline constexpr char BINDINGS_MANIFEST_HASH[] = "{manifest_hash}";\n\n'
        "struct BindingEntry { uint16_t node_id; uint8_t button; const char *event; "
        "uint8_t relay; const char *op; };\n\n"
        f"{table}\n"
        "inline const BindingEntry *binding_find(uint16_t node_id, uint8_t button, const char *event) {\n"
        "  for (std::size_t i = 0; i < BINDINGS_SIZE; i++)\n"
        "    if (BINDINGS[i].node_id == node_id && BINDINGS[i].button == button &&\n"
        "        std::strcmp(BINDINGS[i].event, event) == 0) return &BINDINGS[i];\n"
        "  return nullptr;\n"
        "}\n"
    )


def build_map_export(export_nodes, manifest_hash: str) -> dict:
    """Build the registry/map.json payload (ADR-0009 §7): the read-only export for non-C
    consumers (HVAC controller, dashboards, tooling). schema_version + a deterministic
    map_version marker + the binding manifest_hash + the node list. Nodes are sorted by
    node_id so the export is stable regardless of CSV row order.

    NOTE (ADR-0009 open item 5): the node field shape is provisional — confirm against the
    HVAC controller firmware before freezing. Repo vocabulary (node_id) is used over the
    ADR's shorthand 'id' until then.
    """
    nodes = [
        {
            "node_id": n["node_id"],
            "floor": n["floor"],
            "room": n["room"],
            "board": n["board"],
            "location": n["location"],
            "sensors": n["sensors"],
        }
        for n in sorted(export_nodes, key=lambda n: n["node_id"])
    ]
    body = {"schema_version": 1, "manifest_hash": manifest_hash, "nodes": nodes}
    return {
        "schema_version": 1,
        "map_version": _digest(body),
        "manifest_hash": manifest_hash,
        "nodes": nodes,
    }


def render_ha_package(manifest_hash: str) -> str:
    """Render gateway/ha_manifest_package.yaml (ADR-0009 §4): the GENERATED Home Assistant
    half of the readiness heartbeat, with the manifest hash baked in so HA echoes it
    automatically — retiring the interim hand-paste. Heartbeat only; the ACK automation
    stays hand-maintained in ha_arbitration_automations.yaml until bindings are real and
    manifest-derived (ADR-0009 open item 3, resolved this slice: heartbeat-only package)."""
    return (
        "# =============================================================================\n"
        "# ha_manifest_package.yaml — GENERATED from registry/bindings.yaml by\n"
        "# tools/generate_nodes.py. DO NOT EDIT — re-run the generator after editing bindings.\n"
        "# =============================================================================\n"
        "# Home Assistant package (NOT ESPHome config). It carries the readiness-heartbeat\n"
        "# automation with the binding manifest hash baked in, so HA proves it runs the same\n"
        "# bindings the gateway compiled (ADR-0009 §3/§4). Wire it into HA once, e.g.:\n"
        "#   homeassistant:\n"
        "#     packages:\n"
        "#       canbus_manifest: !include ha_manifest_package.yaml\n"
        "# Regenerating with unchanged bindings produces no diff. The ACK automation stays\n"
        "# hand-maintained in ha_arbitration_automations.yaml (still log-only, ADR-0003).\n"
        "# =============================================================================\n\n"
        "automation:\n"
        "  - id: canbus_gateway_readiness_heartbeat\n"
        '    alias: "CAN gateway: readiness heartbeat"\n'
        "    mode: single\n"
        "    triggers:\n"
        '      - trigger: time_pattern\n'
        '        seconds: "/5"\n'
        "    actions:\n"
        "      - action: esphome.canbus_gateway_ha_readiness_heartbeat\n"
        "        data:\n"
        f'          manifest_hash: "{manifest_hash}"\n'
    )


def write_exports(seen_node_ids, export_nodes, root: Path):
    """Validate registry/bindings.yaml against the registry, then emit every binding-derived
    artifact from one source in one run (ADR-0009 §4/§7): bindings.h (hash + table), map.json
    (read-only export), and ha_manifest_package.yaml (HA echoes the hash). Returns
    (manifest_hash, map_version) — the latter is also compiled into node_map.h for drift
    visibility (§6). Aborts (sys.exit) on an invalid manifest, writing nothing."""
    bindings_path = root / "registry" / "bindings.yaml"
    if not bindings_path.exists():
        print(f"Creating empty {bindings_path} ...")
        bindings_path.write_text("schema_version: 1\nbindings: []\n")

    manifest = bindings.load_bindings(bindings_path)
    errors = bindings.validate(manifest, set(seen_node_ids))
    if errors:
        print("ERROR: invalid binding manifest (registry/bindings.yaml):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    manifest_hash = bindings.canonical_hash(manifest)

    header_path = root / "protocol" / "bindings.h"
    header_path.write_text(render_bindings_header(manifest_hash, manifest["bindings"]))
    print(f"  ✓ {header_path.name}  (binding manifest hash {manifest_hash}, "
          f"{len(manifest['bindings'])} binding(s))")

    map_export = build_map_export(export_nodes, manifest_hash)
    map_path = root / "registry" / "map.json"
    map_path.write_text(json.dumps(map_export, indent=2) + "\n")
    print(f"  ✓ {map_path.name}  (read-only export, map_version {map_export['map_version']}, "
          f"{len(map_export['nodes'])} node(s))")

    ha_path = root / "gateway" / "ha_manifest_package.yaml"
    ha_path.write_text(render_ha_package(manifest_hash))
    print(f"  ✓ {ha_path.name}  (HA readiness heartbeat echoes the hash automatically)")

    return manifest_hash, map_export["map_version"]


def main():
    csv_path = ROOT / "registry" / "nodes.csv"
    out_dir = ROOT / "nodes"
    out_dir.mkdir(exist_ok=True)

    if not csv_path.exists():
        print(f"Creating example {csv_path} ...")
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerows(EXAMPLE_ROWS)
        print(f"  Seeded {csv_path} with current PoC example rows. Review and re-run.\n")
        return

    seen_node_ids = {}
    seen_room_board = {}  # (room, board) -> location, for the commissioned-uniqueness invariant
    count = 0
    floor_groups = {}
    map_entries = []  # (node_id, room, board, location) -> compiled into the gateway's node_map.h
    export_nodes = []  # full rows (incl. floor + sensors) -> registry/map.json (ADR-0009 §7)
    node_files = []  # (path, content, log) staged here, written only after the manifest validates

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        # A misspelled sensors header ("Sensors", " sensors") would silently disable
        # every sensor kit (row.get falls back to 0); a missing column is legitimate
        # legacy format, a near-miss is an error.
        fields = reader.fieldnames or []
        if "sensors" not in fields:
            near = [c for c in fields if c.strip().lower() == "sensors"]
            if near:
                print(f"ERROR: CSV column '{near[0]}' — did you mean 'sensors'?", file=sys.stderr)
                sys.exit(1)
        for row in reader:
            location = row["location"]

            # Optional sensors column (ADR-0006): blank/0 = none, 1 = SHT45+SEN66 kit.
            # Strict on anything else so a registry typo can't silently drop a sensor kit.
            sensors_raw = (row.get("sensors") or "0").strip()
            if sensors_raw not in ("", "0", "1"):
                print(f"ERROR: Invalid sensors value '{sensors_raw}' on CSV row {reader.line_num} "
                      f"(valid: blank, 0, 1)", file=sys.stderr)
                sys.exit(1)
            has_sensors = sensors_raw == "1"

            try:
                node_id = int(row["node_id"])
                floor = int(row["floor"])
                room = int(row["room"])
                board = int(row["board"])
            except ValueError as exc:
                print(f"ERROR: Invalid integer value on CSV row {reader.line_num}: {exc}", file=sys.stderr)
                sys.exit(1)

            if not (0 <= node_id <= NODE_ID_MAX):
                print(f"ERROR: node_id {node_id} out of range (valid: 0-{NODE_ID_MAX})", file=sys.stderr)
                sys.exit(1)

            # node_id uniqueness is the one load-bearing invariant (it is the bus address).
            if node_id in seen_node_ids:
                print(f"ERROR: Duplicate node_id {node_id}: '{location}' vs '{seen_node_ids[node_id]}'", file=sys.stderr)
                sys.exit(1)
            seen_node_ids[node_id] = location

            if not (0 <= room <= ROOM_BOARD_MAX) or not (0 <= board <= ROOM_BOARD_MAX):
                print(f"ERROR: room/board out of range for node_id {node_id} "
                      f"(room={room}, board={board}; valid: 0-{ROOM_BOARD_MAX})", file=sys.stderr)
                sys.exit(1)

            # (room, board) is the gateway's location address; it must be unique among commissioned
            # nodes. (0, 0) is the unassigned placeholder (allocate_node.py seeds it) — exempt it so
            # multiple not-yet-commissioned nodes can coexist.
            if (room, board) != (0, 0):
                if (room, board) in seen_room_board:
                    print(f"ERROR: Duplicate (room, board) ({room}, {board}): "
                          f"'{location}' vs '{seen_room_board[(room, board)]}'", file=sys.stderr)
                    sys.exit(1)
                seen_room_board[(room, board)] = location

            name = f"node{node_id:03d}"
            input_id = can_id(CAT_INPUT, node_id)
            status_id = can_id(CAT_STATUS, node_id)

            yaml_content = TEMPLATE.format(
                name=name,
                node_id=node_id,
                input_id=input_id,
                status_id=status_id,
                sensor_comment=SENSOR_COMMENT if has_sensors else "",
                sensor_pkg=SENSOR_PKG if has_sensors else "",
            )

            sensor_note = "  +sensors" if has_sensors else ""
            floor_groups.setdefault(floor, []).append((node_id, room, board, location))
            map_entries.append((node_id, room, board, location))
            export_nodes.append({
                "node_id": node_id, "floor": floor, "room": room, "board": board,
                "location": location, "sensors": 1 if has_sensors else 0,
            })
            node_files.append((
                out_dir / f"{name}.yaml", yaml_content,
                f"  ✓ {name}.yaml  Input=0x{input_id:08X}  node_id={node_id}  [{location}]{sensor_note}",
            ))
            count += 1

    # Binding-derived exports (ADR-0009 §4/§7): validate the manifest against the registry,
    # then emit bindings.h (hash + fallback table), map.json, and the generated HA package.
    # Run FIRST, before any node artifact is written: write_exports aborts (sys.exit) on an
    # invalid manifest, so validating here means a bad bindings.yaml never leaves nodes/ or
    # node_map.h half-regenerated (validate-before-persist). It also yields map_version, which
    # is compiled into node_map.h for §6 drift visibility.
    manifest_hash, map_version = write_exports(seen_node_ids, export_nodes, ROOT)

    # Manifest validated — now persist the node artifacts.
    for path, content, log in node_files:
        path.write_text(content)
        print(log)

    map_path = ROOT / "protocol" / "node_map.h"
    write_node_map(map_entries, map_version, map_path)
    print(f"  ✓ {map_path.name}  (central node_id -> room/board/name map + map_version {map_version}, compiled into the gateway)")

    print(f"\nGenerated {count} node configs in {out_dir}/")
    print(f"Binding manifest hash: {manifest_hash}  "
          f"(HA echoes it automatically via gateway/ha_manifest_package.yaml)")
    print("\n── CAN ID Map (Input id) ──")
    for floor in sorted(floor_groups):
        label = FLOOR_LABELS.get(floor, f"Floor {floor}")
        print(f"\n  {label} floor:")
        for nid, rm, bd, loc in sorted(floor_groups[floor]):
            print(f"    node_id={nid:<5d}  0x{can_id(CAT_INPUT, nid):08X}  (map-seed R{rm}B{bd})  {loc}")


if __name__ == "__main__":
    main()
