#!/usr/bin/env python3
"""allocate_node.py — allocate the next node_id (persistent monotonic counter) and register it.

A node_id is permanent and never reused (ADR-0007: it is the bus address; a duplicate is a
collision). A high-water mark in firmware/node_id_hwm guarantees monotonic allocation even if
rows are later deleted from nodes.csv. Allocation is identity-only: the row is written with
ALL positioning fields (floor/room/board/location) as placeholders, because none of them are
known until the node is physically mounted. commission.py fills them in later. After allocating,
run generate_nodes.py and flash the board.

Usage:
    python allocate_node.py
"""

import argparse
import csv
from pathlib import Path

HERE = Path(__file__).parent
REGISTRY = HERE.parent / "registry"
CSV_PATH = REGISTRY / "nodes.csv"
HWM_PATH = REGISTRY / "node_id_hwm"
NODE_ID_MAX = 8191  # 13 bits, must match canbus_protocol.h / generate_nodes.py
HEADER = ["node_id", "floor", "room", "board", "location"]


def existing_max() -> int:
    if not CSV_PATH.exists():
        return -1
    with open(CSV_PATH, newline="") as f:
        ids = [int(r["node_id"]) for r in csv.DictReader(f) if r.get("node_id")]
    return max(ids, default=-1)


def main():
    argparse.ArgumentParser(description="Allocate the next node_id and register it in nodes.csv.").parse_args()

    hwm = int(HWM_PATH.read_text().strip()) if HWM_PATH.exists() else -1
    next_id = max(hwm, existing_max()) + 1
    if next_id > NODE_ID_MAX:
        raise SystemExit(f"node_id space exhausted (max {NODE_ID_MAX})")

    new_csv = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new_csv:
            w.writerow(HEADER)
        # Identity-only: floor/room/board/location are placeholders until commissioning.
        w.writerow([next_id, 0, 0, 0, f"node {next_id} (unassigned)"])

    HWM_PATH.write_text(f"{next_id}\n")
    print(f"Allocated node_id {next_id} (floor/room/board/location unassigned — set at commissioning).")
    print("Next: python tools/generate_nodes.py  then flash the board.")


if __name__ == "__main__":
    main()
