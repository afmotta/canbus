#!/usr/bin/env python3
"""allocate_node.py — allocate the next node_id (persistent monotonic counter) and register it.

A node_id is permanent and never reused (ADR-0007: it is the bus address; a duplicate is a
collision). A high-water mark in firmware/node_id_hwm guarantees monotonic allocation even if
rows are later deleted from nodes.csv. The newly allocated node is appended to nodes.csv with
placeholder room/board = 0 ("unassigned") — those are map-seed metadata, filled at commissioning;
set the GPIOs (and optionally a location) now, then run generate_nodes.py and flash the board.

Usage:
    python allocate_node.py --gpio 20,21 [--location "Kitchen"] [--floor 0]
"""

import argparse
import csv
from pathlib import Path

HERE = Path(__file__).parent
CSV_PATH = HERE / "nodes.csv"
HWM_PATH = HERE / "node_id_hwm"
NODE_ID_MAX = 8191  # 13 bits, must match canbus_protocol.h / generate_nodes.py
HEADER = ["node_id", "floor", "room", "board", "location", "gpio_list"]


def existing_max() -> int:
    if not CSV_PATH.exists():
        return -1
    with open(CSV_PATH, newline="") as f:
        ids = [int(r["node_id"]) for r in csv.DictReader(f) if r.get("node_id")]
    return max(ids, default=-1)


def main():
    ap = argparse.ArgumentParser(description="Allocate the next node_id and register it in nodes.csv.")
    ap.add_argument("--gpio", required=True, help="comma-separated button GPIOs, e.g. 20,21")
    ap.add_argument("--location", default="", help="optional friendly location label")
    ap.add_argument("--floor", type=int, default=0)
    args = ap.parse_args()

    hwm = int(HWM_PATH.read_text().strip()) if HWM_PATH.exists() else -1
    next_id = max(hwm, existing_max()) + 1
    if next_id > NODE_ID_MAX:
        raise SystemExit(f"node_id space exhausted (max {NODE_ID_MAX})")

    new_csv = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new_csv:
            w.writerow(HEADER)
        w.writerow([next_id, args.floor, 0, 0,
                    args.location or f"node {next_id} (unassigned)", args.gpio])

    HWM_PATH.write_text(f"{next_id}\n")
    print(f"Allocated node_id {next_id} (room/board = 0 unassigned — set at commissioning).")
    print("Next: python generate_nodes.py  then flash the board.")


if __name__ == "__main__":
    main()
