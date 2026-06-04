---
adr: 0002
title: 'Runtime-assignable node addressing & commissioning (static-IP model)'
status: 'Proposed'
date: '2026-06-04'
deciders: ['Alberto']
author: 'Winston (System Architect)'
dependsOn:
  - 'ADR-0001: Adopt CAN Extended IDs with location-as-address'
relatedDocuments:
  - _bmad-output/planning-artifacts/adrs/0001-can-extended-id-location-as-address.md
  - _bmad-output/planning-artifacts/architecture.md
  - firmware/common/canbus_protocol.h
  - firmware/common/base_node.yaml
  - firmware/gateway.yaml
  - firmware/generate_nodes.py
  - firmware/nodes.csv
---

# ADR-0002: Runtime-assignable node addressing & commissioning (static-IP model)

## Status

**Proposed** — recommended, pending Alberto's go/no-go and resolution of the open items in
[Consequences](#consequences). **Depends on ADR-0001**: this decision assumes the v2
location-as-address layout (`room/board` carried in the Extended CAN ID) and only makes
sense once that is adopted.

Like ADR-0001, this should land **before** the project is declared LIVE, while every node
is still reflashed in lockstep.

## Context

### What we have today

`room_id` and `board_id` are ESPHome **substitutions** — compile-time *text replacement*.
By the time firmware runs there is no variable: `base_node.yaml` emits literal constants
(e.g. `heartbeat_payload(..., 7, 0)`). Changing a node's room or board therefore requires
**editing the registry, regenerating, recompiling, and reflashing** that node.

`generate_nodes.py` already assigns each node a unique identity from `nodes.csv`, and the
protocol already scaffolds a write channel — `MSG_CONFIG_WRITE` / `MSG_CONFIG_ACK` exist in
`canbus_protocol.h`, and `base_node.yaml`'s `on_frame` already decodes a `[key, value]`
config write (today it only logs it).

### The desire

Alberto wants room/board to be **set at build time *and* reassignable in the field via a
gateway command**, surviving reboots — "like assigning static IPs to devices." A board
swap or a re-rooming should become a Home Assistant action, not a reflash-and-redeploy.

### The bootstrap problem this must solve

Under ADR-0001's v2 layout, `room/board` *is* the node's bus address (and its `on_frame`
RX acceptance filter). To *send* a "you are now room 9, board 2" command you must already
be able to **address that specific node** — but the address is the very thing being
changed, and may be wrong or duplicated. That is the chicken-and-egg this ADR resolves.

## Decision

Adopt a **static-IP commissioning model**, with the **gateway/HA as the assignment
authority** (the "DHCP server"):

1. **`room/board` become flash-backed runtime state, not compile-time constants.**
   Implement as ESPHome `globals` with `restore_value: true`, **seeded** by the existing
   build-time substitution as `initial_value`. The build-time value is the *factory
   default*; a gateway command overwrites the persisted value.

2. **Primary workflow: staging pool + remap-all.** Nodes are flashed into a reserved
   "unassigned" room with **progressive board ids**, then every node is remapped to its
   final `(room, board)` after physical installation. This decouples *flashing* from
   *placement* — a batch of boards can be flashed before anyone decides where each goes —
   and the uniqueness of the progressive board id guarantees each staged node is
   **individually reachable** for its remap command. (The alternative — baking the
   *intended* address from `nodes.csv` and treating remap as exception-handling — uses the
   identical mechanism and remains available; see [Alternatives](#alternatives-considered).)

3. **Reserve one `room_id` value as `ROOM_UNASSIGNED`.** A node in this room is
   self-evidently uncommissioned, so the gateway can **auto-discover** new devices and
   prompt for assignment — DHCP-style discovery, for free. Production traffic never uses
   the reserved room, so "staged" and "live" are never ambiguous.

4. **Keep the chip's unique hardware id as a read-only tiebreaker** (the "MAC behind the
   static IP"). The RP2040 exposes a unique 64-bit flash id (`pico_get_unique_board_id`).
   The node never *listens* on it, but **announces** it (in the heartbeat or a discovery
   frame) so the gateway can disambiguate and recover from duplicate-address collisions
   without physically unplugging boards.

5. **Reassignment uses the existing config channel.** Add `KEY_ROOM_ID` / `KEY_BOARD_ID`
   to `MSG_CONFIG_WRITE`; the node persists the global and replies with `MSG_CONFIG_ACK`.
   Provide a **factory-reset** command that re-seeds room/board from the build-time
   default.

6. **Apply semantics under v2 = write-then-reboot.** Because `room/board` keys the
   `on_frame` RX filter and ESPHome configures that filter at `setup()` from a constant,
   a remap **persists the new value and reboots**; the filter is rebuilt from the restored
   value on next boot. The node reappears at its new address; the gateway follows it there.

### Separation of identity (the model in one table)

| Static-IP world | This system | Mutable? | Used to address? |
|---|---|---|---|
| Factory MAC | RP2040 unique flash id | No | No — read-only tiebreaker/diagnostic |
| Static IP set on device | `room/board` (flash-backed globals) | Yes | Yes — the operational bus address |
| Bench-assigned IPs | progressive `board_id` at flash time | (seed) | during commissioning |
| DHCP server + reservation table | gateway / HA | — | the assignment authority & registry |
| Link-local / unconfigured | reserved `ROOM_UNASSIGNED` | — | discovery state |

## Consequences

### Positive

- Room/board changes become a runtime command — no reflash for board swaps or re-rooming.
- Flashing is decoupled from placement: stage a batch, install, then assign.
- New devices are auto-discovered via the reserved room (DHCP-style onboarding).
- A stable node_id is **not** required for the happy path — the progressive logical
  address is unique at commissioning time and serves as the channel for its own remap.
- Reuses the already-scaffolded `MSG_CONFIG_WRITE` / `MSG_CONFIG_ACK` channel.

### Negative / costs

- **Field replacement breaks naive "progressive."** Once nodes are deployed, a spare off
  the shelf can collide with an existing default unless the gateway tracks the next-free
  board id. Mitigation: the gateway *is* the assignment authority and owns that registry.
- **Duplicate-address collisions need recovery.** Two nodes on the same `(room, board)`
  both obey a remap. Mitigation: the announced hardware-id tiebreaker (item 4); physical
  unplug-one is the last-resort fallback (acceptable at home scale).
- **Remap is not instantaneous under v2** — it costs a reboot (write-then-reboot).
- **Persistence caveat on RP2040.** `restore_value` relies on ESPHome preferences, which
  on RP2040 use flash emulation; verify durability and wear behavior on the target board.
- The registry (`nodes.csv`) is no longer the *sole* truth for live room/board — the
  authoritative live map now lives with the gateway/HA. The CSV becomes the seed/default.

### Open items

1. **Pick the reserved `ROOM_UNASSIGNED` value** (e.g. `0` or top of range) and exclude it
   from production room allocation.
2. **Define the assignment-authority/registry** on the gateway/HA side: where the live
   `(hardware_id → room/board)` map lives, and how next-free board ids are tracked.
3. **Confirm the discovery announce**: carry the hardware id in the heartbeat vs. a
   dedicated CAT_SYSTEM discovery frame; define its `MSG_*` type and payload.
4. **Define the config command set & ACK semantics**: `KEY_ROOM_ID`, `KEY_BOARD_ID`,
   factory-reset; whether the gateway addresses commissioning by current `(room, board)`
   or (for recovery) by hardware id.
5. **Verify RP2040 `restore_value` durability** on real hardware.
6. **Validate the write-then-reboot flow** end-to-end with the v2 RX filter (node leaves
   old address, reappears at new one, gateway re-targets).

## Alternatives considered

- **Pre-load the *intended* address (remap = exception).** `generate_nodes.py` bakes the
  planned `(room, board)` from `nodes.csv` as the default; remap only handles cases where
  physical reality differs. Same mechanism, registry stays source of truth. Rejected as
  *primary* because it re-couples flashing to placement decisions; retained as a fully
  supported mode (a node can simply be flashed with a real default instead of the staging
  room).
- **Keep a separate immutable `node_id` as the addressing channel.** The original
  proposal in ADR-0001's discussion. Made unnecessary as a *mandatory* mechanism by the
  progressive-board scheme; its safety benefit is preserved more cheaply by the read-only
  hardware-id tiebreaker.
- **Runtime DHCP-style auto-negotiation of board ids** (identical firmware, addresses
  self-assigned via on-bus negotiation). Rejected as over-engineered for home scale —
  requires a collision-detection protocol and a bus master; the bench-assigned progressive
  seed achieves the same uniqueness with far less complexity.
- **Status quo (reflash to re-room).** Rejected: the motivating requirement is explicitly
  to avoid reflash for a placement change.
