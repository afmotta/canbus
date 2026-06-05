---
adr: 0001
title: 'Adopt CAN Extended IDs with location-as-address (eliminate flat node_id)'
status: 'Accepted'
date: '2026-06-04'
acceptedDate: '2026-06-04'
deciders: ['Alberto']
author: 'Winston (System Architect)'
supersedes:
  - 'architecture.md §Core Architectural Decisions → Node ID space allocation'
  - 'architecture.md §Technical Constraints → ESPHome on_frame constraint (room/board in payload)'
relatedDocuments:
  - _bmad-output/planning-artifacts/adrs/0002-runtime-assignable-node-addressing-and-commissioning.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/project-context.md
  - docs/canbus-smart-home-reference.md
  - firmware/common/canbus_protocol.h
  - firmware/gateway.yaml
  - firmware/common/base_node.yaml
  - firmware/generate_nodes.py
---

# ADR-0001: Adopt CAN Extended IDs with location-as-address (eliminate flat `node_id`)

## Status

**Accepted** — approved by Alberto on 2026-06-04. The open items in the
[Consequences](#consequences) section are now resolved *as part of implementation* (they
are design details internal to the change, not blockers to the decision itself).

Implementation must land **before** production-hardware bring-up and **before** the project
is declared LIVE (while every node is still reflashed in lockstep and no fielded firmware
must stay compatible).

ADR-0002 (runtime-assignable addressing) depends on this decision and remains **Proposed** —
it is *not* part of this implementation.

## Context

### Current design (CAN Protocol v1, 11-bit standard IDs)

The system uses **standard 11-bit CAN IDs** laid out as `[category:2][node_id:9]` — 4
categories, 512 flat node addresses. All semantic data (protocol version, message type,
room, board, button index, event type, uptime, error flags) lives in the **8-byte
payload**. The gateway matches frames by category using mask filtering
(`can_id: 0x200` + `can_id_mask: 0x600`) and decodes room/board/button/event from the
payload bytes.

This created a **three-coordinate location model**:

| Coordinate | Where it lives | Role |
|---|---|---|
| `node_id` (0–399) | CAN ID | the actual bus address |
| `room` + `board` (0–255 each) | payload bytes 2–3 | what Home Assistant actually reasons about |
| `floor` | nowhere on the wire (CSV metadata only) | display / grouping |

`node_id` is bookkeeping that Home Assistant never uses — HA addresses things as
"room 7, board 0." The flat `node_id` exists **only** because 11 bits had no room for
room + board. The CSV (`firmware/nodes.csv`) is the sole place where `node_id` and
`(room, board)` are reconciled, and `generate_nodes.py` carries the validation surface
that this invented coordinate requires (0–399 range check, duplicate-`node_id`
detection, manual floor-range reservation convention).

### The premise that has expired

The original decision to bury room/board in the payload rested on one technical claim,
recorded in `architecture.md:56` and `docs/canbus-smart-home-reference.md:82`:

> "ESPHome's `on_frame` CAN trigger provides the data bytes (`x`) but does not cleanly
> expose the received CAN ID as a lambda variable."

**This is no longer true.** Current ESPHome exposes three variables to the `on_frame`
lambda — `x` (`std::vector<uint8_t>`), **`can_id` (`uint32_t`, the actual received ID)**,
and `remote_transmission_request` (`bool`) — and supports `use_extended_id: true` with a
29-bit `can_id_mask` (default `0x1fffffff`).
Sources: [ESPHome CAN Bus docs](https://esphome.io/components/canbus/),
[esphome-docs source](https://github.com/esphome/esphome-docs/blob/current/content/components/canbus/_index.md).

So putting identity in the CAN ID is now a **design choice**, not a workaround forced by a
tooling limitation. The payload-centric v1 design was correct *at the time*; the
constraint that justified it has since been removed.

### Confirmed precondition

Alberto confirmed (2026-06-04) that **room numbers are globally unique** across the house.
Therefore `(room, board)` is a valid primary key and can serve as the node's address —
no `floor` bits are required in the CAN ID.

Retro-compatibility is **explicitly not a factor**.

## Decision Drivers

- **Model simplicity** — collapse three location coordinates to two; delete a coordinate
  that exists only as a tooling workaround.
- **Alignment with the consumer's mental model** — HA already addresses nodes by
  `(room, board)`; the wire format should too, removing a translation layer.
- **Eliminating a bug class** — `node_id` ↔ `(room, board)` drift is structurally
  possible today and prevented only by CSV discipline.
- **Boring-technology / don't-churn-a-working-system** — counterweight: v1 works, is
  documented, and is internally consistent. Change must earn its keep.
- **Timing** — the cost of a breaking ID change is never lower than now (PoC, 2 nodes,
  pre-LIVE, lockstep reflash).

## Considered Options

1. **Keep current setup** — 11-bit standard IDs, payload-centric, flat `node_id`.
2. **Option A — widen only** — extended IDs but only to enlarge the node address space;
   payload unchanged.
3. **Option B — lift discrete fields into the ID** — `[category][room][board][button][event]`
   in the ID, but keep a flat `node_id` alongside; values (uptime, errors) stay in payload.
4. **Option C — location-as-address** — extended IDs where `(room, board)` **is** the
   address; flat `node_id` is eliminated. (This ADR's recommendation.)

Options A and B were considered and set aside:

- **Option A** buys nothing the project needs — the deployment is ~100 boards across 3
  floors and is nowhere near the existing 512-node ceiling. More address space is not the
  problem. This is churn for no payoff.
- **Option B** captures most of the wire-format benefit but keeps `node_id` as a now-
  redundant coordinate, so it leaves the central bookkeeping cost in place. It is a strict
  subset of C's benefits without C's main win.

The substantive decision is therefore **Option C vs. keeping the current setup**, detailed
below.

## Recommended layout (Option C)

The organising principle: **the ID carries identity + classification (who / what kind);
the payload carries measurements + parameters (how much).** A button press is pure
classification — it has no value — so it becomes a near-empty frame. A heartbeat carries
values (uptime, errors), so only its identity lifts into the ID.

**29-bit Extended ID — INPUT (button) frames:**

```
Bit: 28 27 26 │ 25 .......... 18 │ 17 .......... 10 │ 9 8 7 6 │ 5 4 3 2 │ 1 0
     C  C  C  │ R  R  R  R  R  R  R  R │ B  B  B  B  B  B  B  B │ N N N N │ E E E E │ x x

C = category (3 bits)   — 8 categories (was 2 bits / 4)
R = room     (8 bits)   — 256 rooms
B = board    (8 bits)   — 256 boards
N = button   (4 bits)   — 16 buttons (project uses ≤ 6)
E = event    (4 bits)   — 16 event types (project uses 5)
x = reserved (2 bits)
```

- **INPUT (button):** identity + event fully in the ID. Payload = `[proto_version]`
  (1 byte, kept for forward-compatibility) or DLC = 0.
- **STATUS (heartbeat):** ID = `[category][room][board][0…]`; payload =
  `[proto_version, msg_type, error_flags, uptime_lo, uptime_hi]` (values stay in payload; the
  `msg_type` byte — `MSG_HEARTBEAT` — preserves the uniform `[ver][type]` header and leaves
  room for future STATUS subtypes; matches `canbus_protocol.h` and the protocol reference).
- **OUTPUT (command, gateway → node):** ID =
  `[category:3][room:8][board:8][gateway_id:4][command_subtype:5][rsvd:1]`; payload =
  command parameters. The node's RX acceptance filter matches its own `[OUTPUT][room][board]`
  and is **agnostic to `gateway_id`** (a node accepts a command for its location from
  whichever gateway owns it). The OUTPUT frame has spare room that INPUT does not, so the
  `gateway_id` source field fits here without disturbing the tight INPUT layout. See
  [Gateway addressing](#gateway-addressing-multi-gateway).

Field widths are deliberately right-sized, not copied from the v1 `0–255` habit; the
layout is a one-way door once LIVE, so `button:4` / `event:4` are sized to current needs
plus modest headroom. The 3-bit category leaves room for future message classes
(sensors, presence, bootloader) without a re-cut.

## Gateway addressing (multi-gateway)

POC ships a single gateway, but production may not (raised by Alberto, 2026-06-04). The
v1 design gives gateways **no presence on the wire** — a single gateway silently owns all
node→gateway traffic and is the sole sender of gateway→node commands. That invisibility
is free for one gateway and breaks for two. Decisions captured here:

- **Reason for going multi-gateway: scale / bus-length partitioning** (not redundancy).
  So the demanding shared-bus problems — primary/backup election, overlapping-ownership
  event dedup — are **out of scope**: under partitioning, each node is owned by exactly
  one gateway.
- **Future topology is undecided** (separate per-floor CAN segments *or* one shared bus).
  The design must survive either.

**Separation of concerns:**

- **Node-facing identity stays gateway-agnostic.** `(room, board)` addressing is
  untouched; nodes never encode or filter on a gateway.
- **Gateway identity appears only in gateway-originated frames** — a `gateway_id` *source*
  tag on OUTPUT commands, and (future) a gateway heartbeat under CAT_SYSTEM so HA and peer
  gateways can see each gateway is alive. INPUT / STATUS (node→gateway) frames never carry
  it.

**Why reserve `gateway_id` now (one-way door):** even with a single POC gateway
(`gateway_id = 0`), reserving the field is near-free and is the only part that *cannot* be
added after LIVE. Its purpose differs by topology:

- *Shared bus:* it is a **correctness requirement** — on one physical bus, two
  transmitters must never emit the same 29-bit ID with different payloads simultaneously
  (a latent arbitration/bus-error fault). A distinct source `gateway_id` per gateway
  guarantees OUTPUT IDs are unique per source. It also gives command traceability.
- *Segmented buses:* it is mostly diagnostic/traceability — collisions already dissolve
  because each segment is electrically separate and `(room, board)` is globally unique.

Note: the ID *layout* fixed here is a one-way door, but the `(room, board)` *values* a node
carries need not be compile-time constants — making them runtime-assignable (set at build,
remappable via gateway command, "like static IPs") is a separate decision, see
**[ADR-0002](0002-runtime-assignable-node-addressing-and-commissioning.md)**.

**What stays deferred:** the *logical* ownership map (which gateway commands which rooms),
HA-side command routing (targeting the right ESPHome device), and node→gateway event dedup
— all only needed if a future redundancy (overlap) case appears, which is explicitly not
the current motivation. The reserved field keeps that door open without designing it now.

Width: **`gateway_id:4` (16 gateways)**. Because `gateway_id` lives only in OUTPUT/SYSTEM
frames — never in the tight INPUT layout — widening it costs only one of OUTPUT's two
reserved bits (`command_subtype:5` is preserved). 16 covers per-floor (≈3) through
finer per-room-cluster partitioning with comfortable headroom, chosen over `:3` to avoid
a one-way-door regret at LIVE for a near-zero cost.

## Decision Outcome

**Recommended: adopt Option C.**

For *this* problem the trade-offs favor C:

- The things C gives up — relocation-independent identity and payload headroom — are weak
  for walled-in, fixed boards whose location *is* their identity, and for button events
  that carry no value data.
- The thing C buys — one fewer coordinate, the end of `node_id` bookkeeping and its
  validation/drift surface, and a wire format that matches how HA addresses the world —
  is real and permanent.
- The enabling conditions are all favorable: no retro-compat, lockstep reflash, and
  `can_id` is now readable in the gateway lambda.

The strongest argument against is **not** the design — it is timing risk (see
Consequences → Risks). Mitigation: do it now, before production bring-up.

### Pros / Cons — Option C vs. keeping current setup

**Pros of Option C**

- Deletes the `node_id` coordinate and its entire validation surface (range check,
  duplicate detection, manual floor-range convention in `generate_nodes.py`).
- Makes `node_id` ↔ `(room, board)` drift structurally impossible (location *is* address).
- Gateway decodes room/board/button/event from the `can_id` variable instead of per-field
  payload re-decode; the per-field `!lambda` pattern flagged in `project-context.md:153`
  largely goes away.
- HA-facing command services (`canbus_send_output` / `canbus_send_config`) take
  `room` / `board` — what the automation author already knows — instead of a looked-up
  node number.
- CAN trace reads self-describing identity straight from the ID (`R7 B0 btn2 …`).
- Minor, free: smaller button frames (~67 vs ~111 bits on the wire) and a filter-friendly
  ID that leaves the door open to future per-floor gateway partitioning by room bits.

**Cons of Option C**

- Surrenders relocation-independent identity: re-homing a board to a new room changes its
  address and requires a reflash. (Theoretical for walled-in boards.)
- Introduces a load-bearing invariant not enforced today: **`(room, board)` must be
  unique** — a duplicate becomes an *address collision* (two boards answering one ID), a
  genuine bus fault. New validation is required in `generate_nodes.py`.
- First real hardware bring-up would happen on the *new, unproven* ID format; the
  `on_frame` → `homeassistant.event` chain is itself still uncompiled/untested against
  hardware (`project-context.md:80`). Two unknowns at once unless sequenced carefully.
- Spends the ID bit budget early; field widths are a one-way door once LIVE.

**Pros of keeping current setup**

- It exists, is documented, internally consistent, and every quirk has a recorded
  rationale — zero migration risk (boring technology).
- `node_id` is relocation-independent identity.
- Payload has reserved slack (bytes 6–7) for future per-event *value* data without
  touching the ID.

**Cons of keeping current setup**

- Permanent three-coordinate overhead and its validation, to manage an address HA never
  reads.
- Carries a workaround whose justifying constraint has expired (`can_id` is now readable).
- `node_id` ↔ `(room, board)` drift risk persists, guarded only by CSV discipline.

## Consequences

### If approved — blast radius

A breaking ID-format change with the same cost profile as a breaking payload change
(regenerate + reflash all nodes in lockstep — which the project already does pre-LIVE).
Affected artifacts:

- `firmware/common/canbus_protocol.h` — new ID bit layout; `can_id()` /
  `can_id_category()` / `can_id_node()` replaced by `(category, room, board, …)`
  encode/decode helpers; payload builders/decoders trimmed (button payload shrinks to
  version byte or empty; heartbeat keeps values).
- `firmware/gateway.yaml` — `use_extended_id: true`; `on_frame` masks recomputed for the
  3-bit category at the new bit offsets; decode identity from the `can_id` variable.
- `firmware/common/base_node.yaml` — TX IDs and the OUTPUT RX acceptance filter rebuilt
  from `(category, room, board)`; the OUTPUT filter mask **ignores `gateway_id`** so a node
  accepts commands from whichever gateway owns it.
- `firmware/gateway.yaml` (OUTPUT senders) — `canbus_send_output` / `canbus_send_config`
  stamp the gateway's own `gateway_id` into the OUTPUT ID; POC uses `gateway_id = 0`.
- `firmware/generate_nodes.py` — drop `node_id`; derive the ID from `(room, board)`;
  **add `(room, board)` uniqueness validation**; update the CSV schema and CAN-ID map
  output.
- `firmware/nodes.csv` — schema becomes `floor, room, board, location, gpio_list`
  (no `node_id`).
- **`architecture.md`** — supersede the "Node ID space allocation" decision and the
  "room/board must live in payload" constraint; reconcile the data-flow and naming
  sections. (See "Documents to reconcile" below.)

### Supersession

This ADR (Accepted 2026-06-04) supersedes:

- `architecture.md` → Core Architectural Decisions → **Node ID space allocation**
  (the 0–99 / 100–199 / 200–299 / 300–399 ranges and "floor derivable from node ID").
- `architecture.md` → Technical Constraints → **ESPHome `on_frame` constraint**
  ("CAN ID not cleanly accessible … → room/board must live in payload").

Those sections are no longer authoritative; `architecture.md` is to be reconciled to match
this ADR as part of implementation.

### Open items (must resolve before approval → implementation)

1. **Confirm `(room, board)` global uniqueness operationally**, not just in principle, and
   add the enforcing validation to `generate_nodes.py` as part of the change.
2. **Right-size the field widths** — confirm `room:8 / board:8 / button:4 / event:4 /
   category:3` against realistic ceilings before freezing the layout.
3. **Decide OUTPUT command sub-addressing** — how `gateway_id` + `command_subtype` pack
   into the OUTPUT ID's low bits, and the node RX acceptance-filter mask (which must
   exclude `gateway_id`).
4. **`gateway_id` width set to `:4` (16 gateways)** — costs one OUTPUT reserved bit, keeps
   `command_subtype:5`, leaves headroom past per-floor partitioning. Reserve it in the
   OUTPUT/SYSTEM layout even though POC uses `gateway_id = 0`.
5. **Sequence to de-risk bring-up** — get the v1 `on_frame` → `homeassistant.event` chain
   compiling/working on hardware *first*, or accept debugging the format and the chain
   together.

*Deferred until/unless a redundancy (overlapping-ownership) case appears — explicitly NOT
the current scale-driven motivation:* gateway ownership map, HA-side command routing, and
node→gateway event dedup / primary-backup election. The reserved `gateway_id` field keeps
this addable without re-cutting the ID.

### Risks

- **Timing risk (primary):** doing this after production population multiplies the reflash
  cost from "2 bench nodes" to "every wall." Mitigation: decide and, if yes, implement
  before production bring-up.
- **Address-collision risk:** mitigated by the new `(room, board)` uniqueness validation
  (open item 1).
- **One-way-door risk:** field widths are frozen at LIVE; mitigated by open item 2.

## Notes

This ADR establishes the `adrs/` convention under
`_bmad-output/planning-artifacts/`. The comprehensive `architecture.md` remains the
system-of-record for the overall design; ADRs record point decisions that amend or
supersede specific parts of it over time.
