#!/usr/bin/env python3
"""
generate_nodes.py — Generate ESPHome node configs from the registry CSV.

Usage:
    1. Fill in registry/nodes.csv with your physical layout
    2. Run: python tools/generate_nodes.py
    3. Generated configs appear in nodes/

CSV format:
    node_id,floor,room,board,location
    100,0,7,0,"Ground floor hallway"

Flat node_id model (ADR-0007): node_id is the node's only identity, carried in the 29-bit
Extended CAN ID. It is the ONLY thing flashed into the node. floor/room/board/location are
map-seed metadata for the central node_id -> {...} map on the controller/HA — they are NOT
flashed into the node config (kept here as the registry / map seed).

Every node carries the standard 8-button set (btn0–btn7), SPI/CAN pins, and heartbeat from
packages/base_node.yaml, so each generated file is minimal: just its node_id + debounce_ms
and a single include.
"""

import csv
import sys
from pathlib import Path

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
# CAN IDs (29-bit Extended, computed at runtime from node_id):
#   Input  = 0x{input_id:08X}  (CAT_INPUT,  node -> controller, button events)
#   Status = 0x{status_id:08X}  (CAT_STATUS, node -> controller, heartbeat)
# =============================================================================

substitutions:
  node_id: "{node_id}"
  debounce_ms: "50"

packages:
  base: !include ../packages/base_node.yaml
"""

FLOOR_LABELS = {0: "Ground", 1: "First", 2: "Second", 3: "Third"}
EXAMPLE_ROWS = [
    ["node_id", "floor", "room", "board", "location"],
    [100, 0, 7, 0, "Ground floor hallway"],
    [101, 0, 8, 0, "Ground floor living room"],
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


def write_node_map(entries, path: Path) -> None:
    """Emit the gateway's compiled central map: node_id -> {room, board, name} (ADR-0007)."""
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
        "// =============================================================================\n\n"
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

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            location = row["location"]

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
            )

            out_path = out_dir / f"{name}.yaml"
            with open(out_path, "w") as yf:
                yf.write(yaml_content)

            floor_groups.setdefault(floor, []).append((node_id, room, board, location))
            map_entries.append((node_id, room, board, location))
            print(f"  ✓ {name}.yaml  Input=0x{input_id:08X}  node_id={node_id}  [{location}]")
            count += 1

    map_path = ROOT / "protocol" / "node_map.h"
    write_node_map(map_entries, map_path)
    print(f"  ✓ {map_path.name}  (central node_id -> room/board/name map, compiled into the gateway)")

    print(f"\nGenerated {count} node configs in {out_dir}/")
    print("\n── CAN ID Map (Input id) ──")
    for floor in sorted(floor_groups):
        label = FLOOR_LABELS.get(floor, f"Floor {floor}")
        print(f"\n  {label} floor:")
        for nid, rm, bd, loc in sorted(floor_groups[floor]):
            print(f"    node_id={nid:<5d}  0x{can_id(CAT_INPUT, nid):08X}  (map-seed R{rm}B{bd})  {loc}")


if __name__ == "__main__":
    main()
