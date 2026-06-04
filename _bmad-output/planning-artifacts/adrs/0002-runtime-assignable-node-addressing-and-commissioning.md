---
adr: 0002
title: 'Commissioning of CAN-only button nodes (identical-firmware, press-to-assign)'
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

# ADR-0002: Commissioning of CAN-only button nodes (identical-firmware, press-to-assign)

## Status

**Proposed** — recommended, pending Alberto's go/no-go and resolution of the open items in
[Consequences](#consequences). **Depends on ADR-0001** (location-as-address Extended IDs).

> **Rescoped 2026-06-04, superseded in part by ADR-0003.** This ADR originally covered
> runtime-assignable addressing for *all* nodes — buttons **and** actuators — plus binding
> distribution. ADR-0003 (centralized single-controller) removes distributed actuators
> (relays now hang off one controller via Modbus) and centralizes all binding logic on that
> controller. So the actuator-addressing and binding-distribution material is **dropped**.
> What remains — and is **affirmed as valuable** — is commissioning of the cheap
> **CAN-only button nodes**, the only distributed addressable CAN devices left.

Should land before the project is declared LIVE, while nodes are still reflashed in lockstep.

## Context

### The value: identical firmware → "hand the electrician a box"

The button nodes are many (one per wall switch) and cheap (CAN-only, no Ethernet/OTA). The
operational prize is **byte-identical firmware on every node**: mount them anywhere in any
order, then assign each its `(room, board)` *after* it's on the wall. The alternative —
pre-flashing a distinct address per node — forces per-box labelling, a placement map, and
precise instructions to the installer, with a real risk of two nodes being swapped during a
busy install. The more nodes, the larger the win. **Identical firmware + in-situ assignment
is the requirement this ADR serves.**

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
**ADR-0003 single controller as the commissioning authority** (it already hears all CAN
traffic and bridges to HA's UI).

1. **`room/board` become flash-backed runtime state, not compile-time constants** — ESPHome
   `globals` with `restore_value: true`, defaulting to the reserved unassigned address. A
   config-write overwrites and persists them.

2. **Nodes ship identical and boot *unconfigured*** — reserved `ROOM_UNASSIGNED`. An
   unconfigured node periodically **announces its unique hardware id** (RP2040 64-bit chip
   id, `pico_get_unique_board_id`) on a `CAT_SYSTEM` frame, so the controller/HA can list
   "unknown node, hwid X."

3. **The button is the commissioning selector (press-to-assign).** While unconfigured, a
   button press is treated as *"commission me"* — the node emits its hwid on a system frame.
   The installer presses the button on the node just mounted; it pops up in the app; they
   name it `(room, board)`; the controller writes that address **targeting the hwid** (which
   sidesteps the indistinguishable-address problem); the node persists it and becomes
   configured. Mount everything, walk around pressing buttons, name each as it appears —
   the familiar Zigbee-style "press to pair" ceremony.

   **Generalisation for nodes without a user button (ADR-0006).** Nodes that have no user
   button — e.g. dedicated sensor nodes — carry a small **dedicated commissioning button**
   on the board that serves the identical "commission me" role. The selector is therefore
   "a commissioning button" generally; button nodes reuse a user button, sensor/other nodes
   add a dedicated one. Combined nodes (a button node also hosting sensors) already have a
   usable button.

4. **Hardware id is the commissioning handle** (the "MAC behind the static IP") — used to
   address a node whose logical address is unset, duplicated, or wrong. Never used for
   normal traffic; announced for discovery and recovery.

5. **Re-addressing and factory reset use the same channel.** `KEY_ROOM_ID` / `KEY_BOARD_ID`
   via `SUBTYPE_CONFIG_WRITE`, acknowledged back; a factory-reset command returns a node to
   unconfigured (re-enabling press-to-assign). Re-homing a node is therefore an app action,
   no USB.

6. **Apply semantics = write-then-reboot** where simplest: persist the new address and
   reboot so any address-derived setup is rebuilt cleanly; the node reappears configured.

### Identity model (one table)

| Static-IP analogue | This system | Mutable? | Used to address? |
|---|---|---|---|
| Factory MAC | RP2040 unique chip id | No | Commissioning/recovery handle only |
| Static IP | `room/board` (flash-backed globals) | Yes | The operational bus identity (pub/sub subject) |
| DHCP server + leases | the ADR-0003 controller + HA UI | — | The assignment authority & live registry |
| Link-local / unconfigured | reserved `ROOM_UNASSIGNED` + press-to-assign | — | Discovery/commissioning state |

## Consequences

### Positive

- **Identical firmware** — one image, hand the installer a box, assign after mounting.
- **No pre-labelling / placement map / swap risk.**
- Re-homing and replacement are app actions (config-write by hwid), no USB.
- The single controller (ADR-0003) is the natural authority — no extra infrastructure.
- Reuses the scaffolded `SUBTYPE_CONFIG_WRITE` channel.

### Negative / costs

- New firmware surface on the (otherwise trivial) button nodes: flash-backed address,
  hwid announce, unconfigured-mode press handling, config-write apply.
- **Persistence caveat on RP2040** — `restore_value` uses ESPHome preferences (flash
  emulation on RP2040); verify durability/wear on target hardware.
- The live `(hwid → room/board)` map becomes authoritative on the controller/HA side;
  `nodes.csv` becomes seed/default, not the sole source of truth.
- A duplicate `(room, board)` (e.g. a botched assignment) is still an address collision on
  the pub/sub bus — recoverable via the hwid handle, but it must be detected.

### Open items

1. **Pick the reserved `ROOM_UNASSIGNED` value** and exclude it from production allocation.
2. **Define the discovery/commission frames** — `CAT_SYSTEM` hwid announce + press-to-commission
   frame: message types and payloads.
3. **Define the config command set & ACK** — `KEY_ROOM_ID`, `KEY_BOARD_ID`, factory-reset;
   commissioning addressed by **hwid**, normal management by `(room, board)`.
4. **Where the live registry lives** on the controller/HA side, and duplicate-address detection.
5. **Verify RP2040 `restore_value` durability** on real hardware.
6. **Phasing** — through build/test, static compile-time addressing + manual reflash is fine
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
