#!/usr/bin/env python3
"""commission.py — Phase-1 node commissioning (ADR-0007, static map).

After a node is allocated (allocate_node.py), flashed, mounted, and identified — press its
button and the gateway fires an HA event carrying its node_id; an uncommissioned node also
appears via esphome.canbus_node_unknown — assign its room/board here. This edits the registry
(nodes.csv = the map seed) and regenerates the gateway's compiled node_map.h. Reflash the
gateway to apply (Phase 1 is static; runtime push is a later, pre-go-live phase).

Usage:
    python commission.py list
    python commission.py assign --node-id 102 --room 5 --board 0 [--location "Kitchen"] [--floor 0]
"""

import argparse
import csv
from pathlib import Path

import generate_nodes  # regenerate node_map.h after an edit

HERE = Path(__file__).parent
CSV_PATH = HERE / "nodes.csv"
FIELDS = ["node_id", "floor", "room", "board", "location", "gpio_list"]
MAX_RB = 255  # room/board are uint8 in node_map.h


def read_rows():
    with open(CSV_PATH, newline="") as f:
        return list(csv.DictReader(f))


def write_rows(rows):
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in FIELDS})


def cmd_list(_args):
    rows = read_rows()
    print(f"{'node_id':>8} {'room':>5} {'board':>6} {'floor':>6}  location")
    for r in rows:
        flag = "  (unassigned)" if r["room"] == "0" and r["board"] == "0" else ""
        print(f"{r['node_id']:>8} {r['room']:>5} {r['board']:>6} {r['floor']:>6}  {r['location']}{flag}")


def cmd_assign(args):
    if args.room is not None and not (0 <= args.room <= MAX_RB):
        raise SystemExit(f"room out of range (0-{MAX_RB})")
    if args.board is not None and not (0 <= args.board <= MAX_RB):
        raise SystemExit(f"board out of range (0-{MAX_RB})")

    rows = read_rows()
    match = next((r for r in rows if int(r["node_id"]) == args.node_id), None)
    if match is None:
        raise SystemExit(f"node_id {args.node_id} not in nodes.csv — allocate it first (allocate_node.py).")

    if args.room is not None:
        match["room"] = str(args.room)
    if args.board is not None:
        match["board"] = str(args.board)
    if args.floor is not None:
        match["floor"] = str(args.floor)
    if args.location is not None:
        match["location"] = args.location

    write_rows(rows)
    print(f"Assigned node_id {args.node_id}: room={match['room']} board={match['board']} "
          f"floor={match['floor']} location={match['location']!r}")
    generate_nodes.main()
    print("Regenerated node_map.h — reflash the gateway to apply.")


def main():
    ap = argparse.ArgumentParser(description="Phase-1 node commissioning: assign room/board and regenerate the gateway map.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show the registry / current assignments")
    a = sub.add_parser("assign", help="assign room/board (and optional location/floor) to a node_id")
    a.add_argument("--node-id", type=int, required=True)
    a.add_argument("--room", type=int)
    a.add_argument("--board", type=int)
    a.add_argument("--floor", type=int)
    a.add_argument("--location")
    args = ap.parse_args()
    {"list": cmd_list, "assign": cmd_assign}[args.cmd](args)


if __name__ == "__main__":
    main()
