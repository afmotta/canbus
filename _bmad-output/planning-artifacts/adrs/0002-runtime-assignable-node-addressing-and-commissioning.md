---
adr: 0002
title: 'Commissioning of CAN endpoint nodes (identical-firmware, press-to-assign)'
status: 'Proposed'
date: '2026-06-04'
deciders: ['Alberto']
author: 'Winston (System Architect)'
dependsOn:
  - 'ADR-0001: Adopt CAN Extended IDs with location-as-address'
relatedDocuments:
  - _bmad-output/planning-artifacts/adrs/0001-can-extended-id-location-as-address.md
  - _bmad-output/planning-artifacts/adrs/0003-centralized-single-controller-with-onboard-fallback.md
  - _bmad-output/planning-artifacts/architecture.md
  - firmware/common/canbus_protocol.h
  - firmware/common/base_node.yaml
  - firmware/generate_nodes.py
  - firmware/nodes.csv
---

# ADR-0002: Commissioning of CAN endpoint nodes (identical-firmware, press-to-assign)

## Status

**Superseded by ADR-0007 (2026-06-06).** Under the flat-`node_id` + central-meaning-map
model, identity is fixed at flash and never reassigned, so the runtime address-write/persist/
reboot machinery this ADR specified is no longer needed. *Press-to-identify survives only as a
map-building selector* (it populates the central map; it does not write the node). Retained for
history; see ADR-0007.

**~~Proposed~~** — pending Alberto's go/no-go and resolution of the open items in
[Consequences](#consequences). Depended on ADR-0001 (location-as-address Extended IDs), also superseded.

> **Rescoped 2026-06-04, superseded in part by ADR-0003.** This ADR originally covered
> runtime-assignable addressing for *all* nodes — buttons **and** actuators — plus binding
> distribution. ADR-0003 (centralized single-controller) removes distributed actuators
> (relays now hang off one controller via Modbus) and centralizes all binding logic on that
> controller. So the actuator-addressing and binding-distribution material is **dropped**.
> What remains — and is **affirmed as valuable** — is commissioning of cheap distributed
> **CAN endpoint nodes**: button nodes, combined button+sensor nodes, and dedicated sensor
> nodes introduced by ADR-0006. Distributed actuators remain out of scope.

Should land before the project is declared LIVE, while nodes are still reflashed in lockstep.

## Context

### The value: identical firmware → "hand the electrician a box"

The button nodes are many (one per wall switch) and cheap (CAN-only, no Ethernet/OTA).
ADR-0006 adds dedicated sensor nodes and combined button+sensor nodes with the same
commissioning need. The operational prize is **byte-identical firmware per node profile**:
mount nodes anywhere in any order, then assign each its `(room, board)` *after* it's on the
wall. The alternative — pre-flashing a distinct address per node — forces per-box labelling,
a placement map, and precise instructions to the installer, with a real risk of two nodes
being swapped during a busy install. The more nodes, the larger the win. **Identical
firmware + in-situ assignment is the requirement this ADR serves.**

### What we have today

`room_id`/`board_id` are ESPHome **substitutions** — compile-time text replaced into
literals. Changing a node's address means edit-registry → regenerate → recompile → reflash
*that* node. `canbus_protocol.h` already scaffolds a config-write channel
(`SUBTYPE_CONFIG_WRITE`), and the node `on_frame` already decodes a `[key, value]` write
(today it only logs it).

### The bootstrap problem

Identical firmware means every node boots with the **same** default address → on the bus
they are indistinguishable → you cannot target one to assign it. The original ADR solved
this with *progressive* board ids (a staging pool) — but that requires **non-identical**
firmware, defeating the deployment goal. We need a way to single out one physical,
not-yet-addressed node.

## Decision

Adopt **identical-firmware commissioning with button-press identification**, with the
**ADR-0003 single controller + HA UI as the commissioning authority and live registry owner**
for all CAN endpoint nodes. Other controllers, including the ADR-0006 HVAC controller, may
consume CAN traffic and registry metadata but do not assign or re-home nodes.

1. **`room/board` become flash-backed runtime state, not compile-time constants** — ESPHome
   `globals` with `restore_value: true`, defaulting to the reserved unassigned address:
   `ROOM_UNASSIGNED = 255`, `BOARD_UNASSIGNED = 255`. Room `255` is excluded from production
   allocation; `room == ROOM_UNASSIGNED` is the unconfigured test.

2. **Nodes ship identical and boot *unconfigured*** — reserved `ROOM_UNASSIGNED`. An
   unconfigured node periodically **announces its unique hardware id** (RP2040 64-bit chip
   id, `pico_get_unique_board_id`) using the `CAT_SYSTEM` commissioning subprotocol
   defined below, so the controller/HA can list "unknown node, hwid X."

3. **The button is the commissioning selector (press-to-assign).** While unconfigured, a
   button press is treated as *"commission me"* — the node emits its hwid on a system frame.
   The installer presses the button on the node just mounted; it pops up in the app; they
   name it `(room, board)`; the controller selects the node by full hwid, then writes the
   address through a short-lived commissioning transaction (which sidesteps the
   indistinguishable-address problem); the node persists it and becomes configured. Mount
   everything, walk around pressing buttons, name each as it appears — the familiar
   Zigbee-style "press to pair" ceremony.

   **Generalisation for nodes without a user button (ADR-0006).** Nodes that have no user
   button — e.g. dedicated sensor nodes — carry a small **dedicated commissioning button**
   on the board that serves the identical "commission me" role. The selector is therefore
   "a commissioning button" generally; button nodes reuse a user button, sensor/other nodes
   add a dedicated one. Combined nodes (a button node also hosting sensors) already have a
   usable button.

4. **Hardware id is the commissioning handle** (the "MAC behind the static IP") — used to
   address a node whose logical address is unset, duplicated, or wrong. Never used for
   normal traffic; announced for discovery and recovery.

5. **Address assignment is atomic.** Commissioning does **not** write `KEY_ROOM_ID` and
   `KEY_BOARD_ID` independently. It uses one `SYS_SET_ADDRESS(room, board)` command inside a
   selected hwid transaction, then persists `{magic, schema_version, room, board, checksum}`
   as one address record. This avoids a half-written room/board pair surviving reboot.

6. **Re-addressing and factory reset use the same hwid channel.** A configured node still
   listens for `CAT_SYSTEM` selection by its hwid for recovery and re-homing. Normal
   non-address management can continue to use `(room, board)`-addressed `CAT_OUTPUT` config
   commands, but address recovery never depends on the possibly-wrong logical address.

7. **Apply semantics = write-then-reboot** where simplest: persist the new address and
   reboot so any address-derived setup is rebuilt cleanly; the node reappears configured.

8. **One commissioning authority.** The ADR-0003 controller/HA UI owns the live
   `(hwid → room/board/profile)` registry. The HVAC controller introduced by ADR-0006 is a
   `CAT_SENSOR` consumer only; it decodes sensor frames and may read exported registry
   metadata for naming, but it never allocates addresses.

### Identity model (one table)

| Static-IP analogue | This system | Mutable? | Used to address? |
|---|---|---|---|
| Factory MAC | RP2040 unique chip id | No | Commissioning/recovery handle only |
| Static IP | `room/board` (flash-backed globals) | Yes | The operational bus identity (pub/sub subject) |
| DHCP server + leases | the ADR-0003 controller + HA UI | — | The assignment authority & live registry |
| Link-local / unconfigured | `ROOM_UNASSIGNED = 255`, `BOARD_UNASSIGNED = 255` + press-to-assign | — | Discovery/commissioning state |

### Commissioning `CAT_SYSTEM` subprotocol

Commissioning frames do **not** use `(room, board)` in the ID, because unconfigured or
mis-addressed nodes cannot be reached by their logical address. `CAT_SYSTEM` commissioning
frames reserve the top category bits and use the remaining bits as a management namespace:

```
Bit: 28 27 26 │ 25 24 23 22 │ 21 .................... 0
   C  C  C  │ S  S  S  S  │ H H H H H H H H H H H H H H H H H H H H H H
C = CAT_SYSTEM (0)    S = system_subtype (4 bits)    H = hwid_hash22
```

`hwid_hash22 = fnv1a32(hwid[0..7]) & 0x3FFFFF`. The hash is a routing/arbitration handle
only; the **full 64-bit hwid is authoritative** whenever identity matters. Periodic
unconfigured announcements use randomized jitter/backoff so two nodes with the same system
ID do not repeatedly transmit different payloads at the same instant. If the controller ever
observes two full hwids with the same `hwid_hash22`, it flags that as a commissioning
collision and refuses automatic assignment until manually resolved.

| Subtype | Name | Direction | Payload | Semantics |
|---:|---|---|---|---|
| `0x1` | `SYS_HWID_ANNOUNCE` | node → controller | `hwid[0..7]` | Periodic unconfigured discovery. Payload is the raw 64-bit hwid; this is the deliberate exception to the usual `[PROTO_V1, ...]` prefix because CAN DLC is 8 bytes. |
| `0x2` | `SYS_COMMISSION_REQUEST` | node → controller | `hwid[0..7]` | Emitted on commissioning-button press; same identity semantics as announce, but promoted in the UI. |
| `0x3` | `SYS_COMMISSION_SELECT` | controller → nodes | `hwid[0..7]` | All nodes with matching `hwid_hash22` compare full hwid. Exactly the matching node enters a selected state for a short timeout (e.g. 30 s) and ACKs. |
| `0x4` | `SYS_SET_ADDRESS` | controller → selected node | `[PROTO_V1, txid, room, board, flags, crc8, 0, 0]` | Atomic address assignment. The node accepts only while selected for the same `txid`, validates `room != ROOM_UNASSIGNED`, persists the address record, ACKs durable commit, then reboots. |
| `0x5` | `SYS_FACTORY_RESET` | controller → selected node | `[PROTO_V1, txid, flags, 0, 0, 0, 0, 0]` | Clears the persisted address record and returns the node to unconfigured mode. |
| `0x6` | `SYS_ACK` | node → controller | `[PROTO_V1, txid, acked_subtype, status, room, board, 0, 0]` | `status`: `0=OK`, `1=BAD_PROTO`, `2=NOT_SELECTED`, `3=INVALID_ADDRESS`, `4=PERSIST_FAIL`, `5=HWID_MISMATCH`. |

Configured and unconfigured nodes both listen for `SYS_COMMISSION_SELECT` targeting their
full hwid; only unconfigured nodes emit periodic `SYS_HWID_ANNOUNCE`. This keeps recovery
possible even when a configured node's `(room, board)` is duplicated or wrong.

## Consequences

### Positive

- **Identical firmware** — one image, hand the installer a box, assign after mounting.
- **No pre-labelling / placement map / swap risk.**
- Re-homing and replacement are app actions (config-write by hwid), no USB.
- The single controller (ADR-0003) is the natural authority — no extra infrastructure.
- Reuses the scaffolded `SUBTYPE_CONFIG_WRITE` channel.

### Negative / costs

- New firmware surface on the endpoint nodes: flash-backed address,
  hwid announce, unconfigured-mode press handling, config-write apply.
- **Persistence caveat on RP2040** — `restore_value` uses ESPHome preferences (flash
  emulation on RP2040); verify durability/wear on target hardware.
- The live `(hwid → room/board)` map becomes authoritative on the controller/HA side;
  `nodes.csv` becomes seed/default, not the sole source of truth.
- A duplicate `(room, board)` (e.g. a botched assignment) is still an address collision on
  the pub/sub bus — recoverable via the hwid handle, but it must be detected.

### Open items

1. **Implement the `CAT_SYSTEM` commissioning helpers** in `canbus_protocol.h` — subtype
   constants, `fnv1a32`/`hwid_hash22`, ID builders/decoders, CRC8, and ACK/status constants.
2. **Where the live registry lives** on the controller/HA side, including duplicate
   `(room, board)` detection and duplicate `hwid_hash22` handling.
3. **Verify RP2040 `restore_value`/preferences durability** on real hardware; if ESPHome
   globals are insufficient for an atomic address record, use a small custom persistence
   component or dual-slot record.
4. **Phasing** — through build/test, static compile-time addressing + manual reflash is fine
   (per ADR-0003); this runtime commissioning is a **pre-go-live** deliverable.

## Alternatives considered

- **Progressive board ids / staging pool (the original primary).** Rejected: requires
  non-identical firmware, which defeats the "hand the electrician one box" goal. Press-to-assign
  achieves in-situ assignment *with* identical firmware.
- **Pre-load the intended `(room, board)` per node** (reflash each with its address). Works,
  and is exactly the POC's `generate_nodes.py` flow — fine for the bench, rejected as the
  production primary because of the labelling/placement/swap burden at scale.
- **Boxes pre-sorted by room** (identical-ish firmware grouped per room). A partial
  middle-ground Alberto noted; still needs sorting and per-box handling. Press-to-assign is
  strictly simpler.
- **Status quo (reflash to re-room).** Rejected: motivating requirement is to avoid USB
  reflash for placement changes in the field.

> **Out of scope (moved by ADR-0003):** actuator addressing (no distributed CAN actuators —
> relays are Modbus off the single controller) and binding-table distribution (bindings live
> on the controller, pushed over its API, not commissioned over CAN).
