---
adr: 0007
title: 'Flat node_id identity with central meaning map (supersedes location-as-address)'
status: 'Proposed'
date: '2026-06-06'
deciders: ['Alberto']
author: 'Winston (System Architect)'
supersedes:
  - 'ADR-0001: Adopt CAN Extended IDs with location-as-address'
  - 'ADR-0002: Commissioning of CAN-only button nodes'
relatedDocuments:
  - _bmad-output/planning-artifacts/adrs/0001-can-extended-id-location-as-address.md
  - _bmad-output/planning-artifacts/adrs/0002-runtime-assignable-node-addressing-and-commissioning.md
  - _bmad-output/planning-artifacts/adrs/0003-centralized-single-controller-with-onboard-fallback.md
  - _bmad-output/planning-artifacts/adrs/0004-information-model-and-addressing-vs-knx.md
  - _bmad-output/planning-artifacts/adrs/0006-sensor-data-transport-over-can.md
---

# ADR-0007: Flat node_id identity with central meaning map

## Status

**Proposed** — supersedes **ADR-0001** (location-as-address) and **ADR-0002** (runtime
address commissioning). Reached after an extended exploration of onboarding options; this
is the model that resolves onboarding by *removing* node-side identity state rather than
engineering around it.

## Context

ADR-0001 made `(room, board)` the node's CAN address ("location is the address"). Two later
decisions undercut its premise:

- **ADR-0003 centralized control** — one controller hears every frame and translates it for
  HA. Once control is centralized, location-in-the-ID buys almost nothing (its main value
  was distributed actuators filtering by location, which no longer exist); the controller
  maps whatever id it sees.
- **Onboarding** — every location-bearing scheme forced either per-node placement decisions
  at flash time, or runtime address reassignment over CAN with node-side flash persistence
  and write-then-reboot (ADR-0002). All of it was complexity in service of putting *meaning*
  on the node.

The cleaner pattern — and the one this ADR adopts — is the classic device model (and KNX's):
**a node has a permanent, meaningless id; the application assigns meaning centrally.**

## Decision

1. **Node identity = a single flat `node_id`**, assigned at flash time, carrying no meaning.
   **`room_id` / `board_id` are removed from the node entirely.**
2. **ID structure reverts to standard 11-bit** `[category:2][node_id:9]` (512 nodes —
   ample for a house); all content (button index, event type, sensor value, heartbeat
   fields) lives in the 8-byte payload. This drops ADR-0001's Extended-ID layout and is the
   original v1 ID structure **minus** the room/board payload fields (which also go away).
   *(Width sub-decision: 9-bit node_id / standard frames is the simplest sufficient choice;
   widen to Extended IDs only if 512 nodes is ever exceeded — it won't be.)*
3. **Meaning lives in a central map** on the controller/HA: `node_id → { room, board,
   behavior, bindings }`, defined and edited **after** install. The node never knows or
   stores its location.
4. **Onboarding = build the map** (no node writes, ever):
   - Flash a **progressive `node_id`** via a script with a **persistent monotonic counter**
     (or next-free-on-bus); print it on a board label.
   - Mount boards anywhere.
   - **Button nodes:** *press-to-identify* — press a button, the controller surfaces the
     `node_id`, assign it to a room/behavior in a small CLI/app. No tracking required.
   - **Button-less nodes (sensors):** read the **printed `node_id`** at install and record
     its placement. (Possible because *we* mint the id at flash time — unlike an intrinsic
     hwid, it can be labelled.)
   - The CLI/app reaches the bus through the controller's commissioning service.
5. **No runtime node_id reassignment, no node-side persistence beyond the flashed id, no
   write-then-reboot, no per-node commissioning state machine.** Re-homing or behaviour
   changes are central-map edits; the node is never touched after flashing.
6. **Fallback bindings (ADR-0003)** key on `(node_id, button)`; the controller resolves
   `node_id → room` for HA/display.

## Consequences

### Positive
- **Drastically simpler node firmware** — dumb, effectively stateless (id baked at flash).
  No config-write channel, no flash persistence, no reboot dance.
- **Onboarding is pure map-building** — the problem is removed, not solved.
- **No hashing, no collisions** — a script-allocated sequential id fits the ID directly.
- **Fits ADR-0003 and ADR-0004's KNX conclusion** — `node_id` = individual (physical)
  address; the central map = function assignment (KNX group/ETS). Fully realises the
  dual-identity split ADR-0004 was circling.
- **No node_id↔room drift** — room/board exist *only* in the map; one node-side coordinate.
- **Sensor-node identification solved** via the printed id (the gap that broke press-to-assign).

### Negative / costs
- **Reverts ADR-0001** — the Extended-ID/location-as-address implementation (PR #6) is
  abandoned; main's v1 `node_id` firmware is closer to this direction.
- **The central map becomes critical config** — back it up; it is rebuildable (re-identify
  each node) but losing it loses all meaning until then. (Trade vs location-as-address,
  where a node self-described its room.)
- **CAN traces are not human-readable** (show `node_id`, not location) — tooling compensates.
- **Still a per-board flash** (unique `node_id`) — not identical firmware; but the id is
  permanent (no later reassignment), which is strictly simpler than the staging-pool path.
- **`node_id` allocation hygiene** — monotonic counter / next-free; spares need fresh ids;
  a duplicate is a true address collision (the one invariant that survives).

## Impact on other ADRs
- **ADR-0001** → **Superseded.**
- **ADR-0002** → **Superseded** (no runtime reassignment; press-to-identify survives only as
  a map-building selector, not a node write).
- **ADR-0004** → revised: **D1 reversed** — button/event move **back to the payload**
  (centralization removes the in-ID filtering rationale); **D3** priority sub-ordering is now
  by `node_id` within a category (same benign acceptance). The KNX-alignment conclusion
  strengthens.
- **ADR-0006** → revised: sensor frames are keyed by **`node_id`** (`[CAT_SENSOR][node_id]`),
  with `measurement_type` + value in the payload; room is derived centrally.
- **ADR-0003 / ADR-0005** → unaffected (controller is the central authority either way;
  `node_id` is globally unique, hence segment-agnostic across bridged buses).

## Alternatives considered (the journey)
- **Location-as-address (ADR-0001).** Superseded — its benefit evaporated under centralization.
- **Identical firmware + intrinsic hwid (option 2a).** Rejected — 64-bit hwid blows the
  8-byte payload budget and a truncated/hashed id reintroduces collision math.
- **Progressive temp-id + runtime reassignment (ADR-0002 staging).** Rejected — requires
  persist-over-CAN and write-then-reboot on wall-mounted boards.
- **Flat `node_id` + central map (this).** Chosen — minimal node state, no reassignment, no
  collisions, fits the centralized + KNX direction.

## Open items
1. Confirm the standard-11-bit / 9-bit-`node_id` width (vs Extended).
2. Define the central-map schema + the controller's commissioning service (list/identify
   nodes, edit the map) and its backup.
3. `node_id` allocation tooling (persistent counter / next-free) + label printing.
4. Implementation: trim main's v1 payloads (drop room/board), re-key ADR-0006 sensors on
   `node_id`, build the map + CLI/app. (Firmware delta is small relative to PR #6.)
