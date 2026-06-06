#!/usr/bin/env python3
"""
generate_nodes.py — Generate ESPHome node configs from a registry CSV.

Usage:
    1. Fill in nodes.csv with your physical layout
    2. Run: python generate_nodes.py
    3. Generated configs appear in nodes/

CSV format:
    node_id,floor,room,board,location,gpio_list
    100,0,7,0,"Ground floor hallway","20,21"

node_id is the flat CAN bus address (0-399).
floor/room/board are metadata carried in the payload for HA.
"""

import csv
import sys
from pathlib import Path

TEMPLATE = """\
# =============================================================================
# Node: {name} — ID {node_id}
# =============================================================================
# Floor:    {floor_label}
# Location: {location}
# Room:     {room}, Board: {board}
# Buttons:  {num_buttons} (GPIO {gpio_summary})
# CAN IDs:  Input  = 0x{input_id:03X}  (CAT_INPUT,  node → gateway, button events)
#           Status = 0x{status_id:03X}  (CAT_STATUS, node → gateway, heartbeat)
#           Output = 0x{output_id:03X}  (CAT_OUTPUT, gateway → node, commands / RX filter)
# =============================================================================

substitutions:
        node_name: "{name}"
        node_id: "{node_id}"
        room_id: "{room}"
        board_id: "{board}"
        input_can_id: "0x{input_id:03X}"
        output_can_id: "0x{output_id:03X}"
        status_can_id: "0x{status_id:03X}"
        debounce_ms: "50"
        can_cs_pin: "GPIO9"
        can_clk_pin: "GPIO2"
        can_mosi_pin: "GPIO3"
        can_miso_pin: "GPIO4"
        # No can_int_pin: the ESPHome mcp2515 component polls over SPI and exposes no
        # interrupt-pin config. The hardware INT line is GPIO11 (see README OQ-2).
        can_clock: "16MHZ"

esphome:
  name: ${{node_name}}
  friendly_name: "{location}"

rp2040:
  board: rpipico

logger:
  level: DEBUG

packages:
  base: !include ../common/base_node.yaml
{button_packages}\
"""

BUTTON_PKG = '  btn{idx}: !include {{ file: ../common/button.yaml, vars: {{ button_index: "{idx}", button_gpio: "{gpio}" }} }}'

FLOOR_LABELS = {0: "Ground", 1: "First", 2: "Second", 3: "Third"}
EXAMPLE_ROWS = [
    ["node_id", "floor", "room", "board", "location", "gpio_list"],
    [100, 0, 7, 0, "Ground floor hallway", "20,21"],
    [101, 0, 8, 0, "Ground floor living room", "20,21"],
]


def can_id(category: int, node_id: int) -> int:
    return ((category & 0x03) << 9) | (node_id & 0x1FF)


def main():
    csv_path = Path(__file__).parent / "nodes.csv"
    out_dir = Path(__file__).parent / "nodes"
    out_dir.mkdir(exist_ok=True)

    if not csv_path.exists():
        print(f"Creating example {csv_path} ...")
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerows(EXAMPLE_ROWS)
        print(f"  Seeded {csv_path} with current PoC example rows. Review and re-run.\n")
        return

    seen_node_ids = {}
    count = 0
    floor_groups = {}

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            location = row["location"]

            try:
                node_id = int(row["node_id"])
                floor = int(row["floor"])
                room = int(row["room"])
                board = int(row["board"])
                gpios = [int(g.strip()) for g in row["gpio_list"].split(",")]
            except ValueError as exc:
                print(f"ERROR: Invalid integer value on CSV row {reader.line_num}: {exc}", file=sys.stderr)
                sys.exit(1)

            if not (0 <= node_id <= 399):
                print(f"ERROR: Node ID {node_id} out of range (valid: 0–399)", file=sys.stderr)
                sys.exit(1)
            if not (0 <= room <= 255):
                print(f"ERROR: Room {room} out of range (valid: 0–255)", file=sys.stderr)
                sys.exit(1)
            if not (0 <= board <= 255):
                print(f"ERROR: Board {board} out of range (valid: 0–255)", file=sys.stderr)
                sys.exit(1)
            if len(gpios) > 6:
                print(f"ERROR: Too many GPIOs for node {node_id}: max 6, got {len(gpios)}", file=sys.stderr)
                sys.exit(1)
            if len(set(gpios)) != len(gpios):
                print(f"ERROR: Duplicate GPIO in node {node_id}: {row['gpio_list']}", file=sys.stderr)
                sys.exit(1)

            if node_id in seen_node_ids:
                print(f"ERROR: Duplicate node_id {node_id}: '{location}' vs '{seen_node_ids[node_id]}'", file=sys.stderr)
                sys.exit(1)
            seen_node_ids[node_id] = location

            name = f"node{node_id:03d}"
            input_id = can_id(1, node_id)
            output_id = can_id(2, node_id)
            status_id = can_id(3, node_id)

            button_lines = [BUTTON_PKG.format(idx=idx, gpio=gpio) for idx, gpio in enumerate(gpios)]

            yaml_content = TEMPLATE.format(
                name=name,
                node_id=node_id,
                floor_label=FLOOR_LABELS.get(floor, f"Floor {floor}"),
                room=room,
                board=board,
                location=location,
                num_buttons=len(gpios),
                gpio_summary=",".join(str(g) for g in gpios),
                input_id=input_id,
                output_id=output_id,
                status_id=status_id,
                button_packages="\n".join(button_lines) + "\n",
            )

            out_path = out_dir / f"{name}.yaml"
            with open(out_path, "w") as yf:
                yf.write(yaml_content)

            floor_groups.setdefault(floor, []).append((node_id, room, board, location, len(gpios)))
            print(f"  ✓ {name}.yaml  CAN=0x{input_id:03X}  R{room}B{board}  {len(gpios)} btn  [{location}]")
            count += 1

    print(f"\nGenerated {count} node configs in {out_dir}/")
    print("\n── CAN ID Map ──")
    for floor in sorted(floor_groups):
        label = FLOOR_LABELS.get(floor, f"Floor {floor}")
        print(f"\n  {label} floor:")
        for nid, rm, bd, loc, nb in sorted(floor_groups[floor]):
            cid = can_id(1, nid)
            print(f"    #{nid:3d}  0x{cid:03X}  R{rm}B{bd}  {nb} btn  {loc}")


if __name__ == "__main__":
    main()
