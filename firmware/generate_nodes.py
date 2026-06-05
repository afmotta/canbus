#!/usr/bin/env python3
"""
generate_nodes.py — Generate ESPHome node configs from a registry CSV.

Usage:
    1. Fill in nodes.csv with your physical layout
    2. Run: python generate_nodes.py
    3. Generated configs appear in nodes/

CSV format (ADR-0001 — Extended IDs, location-as-address):
    floor,room,board,location,gpio_list
    0,7,0,"Ground floor hallway","20,21"

There is no node_id: a node's CAN address IS its (room, board), encoded directly into
the 29-bit Extended ID. (room, board) MUST be unique across the whole registry — a
duplicate is a physical address collision (two boards answering one ID), which this
script rejects.
"""

import csv
import sys
from pathlib import Path

TEMPLATE = """\
# =============================================================================
# Node: {name} — Room {room}, Board {board}
# =============================================================================
# Floor:    {floor_label}
# Location: {location}
# Buttons:  {num_buttons} (GPIO {gpio_summary})
# CAN IDs (29-bit Extended, location-as-address):
#   Input  base = 0x{input_id:08X}  (CAT_INPUT,  node → gateway; button/event in low bits)
#   Status      = 0x{status_id:08X}  (CAT_STATUS, node → gateway, heartbeat)
#   Output RX   = 0x{output_id:08X}  (CAT_OUTPUT, gateway → node; mask 0x1FFFFC00)
# =============================================================================

substitutions:
        node_name: "{name}"
        room_id: "{room}"
        board_id: "{board}"
        output_can_id: "0x{output_id:08X}"
        status_can_id: "0x{status_id:08X}"
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
    ["floor", "room", "board", "location", "gpio_list"],
    [0, 7, 0, "Ground floor hallway", "20,21"],
    [0, 8, 0, "Ground floor living room", "20,21"],
]

# --------------- ID field shifts (must match canbus_protocol.h) ---------------
CAT_SHIFT = 26
ROOM_SHIFT = 18
BOARD_SHIFT = 10
CAT_INPUT, CAT_OUTPUT, CAT_STATUS = 1, 2, 3


def can_addr(category: int, room: int, board: int) -> int:
    """Shared high field [category][room][board] of the 29-bit Extended ID."""
    return ((category & 0x07) << CAT_SHIFT) | ((room & 0xFF) << ROOM_SHIFT) | ((board & 0xFF) << BOARD_SHIFT)


def node_name(room: int, board: int) -> str:
    return f"node-r{room}-b{board}"


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

    seen_rb = {}
    count = 0
    floor_groups = {}

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            location = row["location"]

            try:
                floor = int(row["floor"])
                room = int(row["room"])
                board = int(row["board"])
                gpios = [int(g.strip()) for g in row["gpio_list"].split(",")]
            except (ValueError, KeyError) as exc:
                print(f"ERROR: Invalid/missing value on CSV row {reader.line_num}: {exc}", file=sys.stderr)
                sys.exit(1)

            if not (0 <= room <= 255):
                print(f"ERROR: Room {room} out of range (valid: 0–255)", file=sys.stderr)
                sys.exit(1)
            if not (0 <= board <= 255):
                print(f"ERROR: Board {board} out of range (valid: 0–255)", file=sys.stderr)
                sys.exit(1)
            if len(gpios) > 6:
                print(f"ERROR: Too many GPIOs for R{room}B{board}: max 6, got {len(gpios)}", file=sys.stderr)
                sys.exit(1)
            if len(set(gpios)) != len(gpios):
                print(f"ERROR: Duplicate GPIO in R{room}B{board}: {row['gpio_list']}", file=sys.stderr)
                sys.exit(1)

            # Load-bearing invariant (ADR-0001): (room, board) is the bus address and must
            # be unique. A duplicate would be an address collision — two boards on one ID.
            if (room, board) in seen_rb:
                print(f"ERROR: Duplicate (room, board) = ({room}, {board}): "
                      f"'{location}' vs '{seen_rb[(room, board)]}'", file=sys.stderr)
                sys.exit(1)
            seen_rb[(room, board)] = location

            name = node_name(room, board)
            input_id = can_addr(CAT_INPUT, room, board)
            output_id = can_addr(CAT_OUTPUT, room, board)
            status_id = can_addr(CAT_STATUS, room, board)

            button_lines = [BUTTON_PKG.format(idx=idx, gpio=gpio) for idx, gpio in enumerate(gpios)]

            yaml_content = TEMPLATE.format(
                name=name,
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

            floor_groups.setdefault(floor, []).append((room, board, location, len(gpios), output_id))
            print(f"  ✓ {name}.yaml  OutRX=0x{output_id:08X}  R{room}B{board}  {len(gpios)} btn  [{location}]")
            count += 1

    print(f"\nGenerated {count} node configs in {out_dir}/")
    print("\n── CAN ID Map (Output RX filter base) ──")
    for floor in sorted(floor_groups):
        label = FLOOR_LABELS.get(floor, f"Floor {floor}")
        print(f"\n  {label} floor:")
        for rm, bd, loc, nb, oid in sorted(floor_groups[floor]):
            print(f"    R{rm:3d}B{bd:<3d}  Out=0x{oid:08X}  {nb} btn  {loc}")


if __name__ == "__main__":
    main()
