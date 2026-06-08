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
2. **ID structure: 29-bit Extended IDs** — `[category:4][node_id:13][reserved:12]`, uniform
   across all categories:
   - **`category:4`** (16 values) — ends the 2-bit squeeze and gives clean slots + arbitration
     priority to `SYSTEM, INPUT, OUTPUT, STATUS, SENSOR, CONFIG, DISCOVERY, BOOTLOADER`
     (~8 used, ~8 spare, addable later with **no re-cut**). One value is reserved as
     **`CAT_EXTENDED`** — an escape that defers the real class to a payload subtype byte, so
     the field never needs widening even if classes ever exceed 16.
   - **`node_id:13`** (8192) — the flat identity; source for node→controller frames,
     destination for controller→node frames. A house needs far less; this is comfort.
   - **`reserved:12`** — held for future per-category low fields (e.g. in-ID `button`/`event`,
     `measurement_type`, or a `source_ctrl` tag) **only once a concrete consumer can
     hardware-filter on them**. No such consumer exists today (the central controller reads
     every frame; bridges forward-all), so the low bits stay reserved rather than freezing
     speculative sub-field widths at the LIVE one-way door.

   **All message content stays in the 8-byte payload** — button index, event type, sensor
   value, command subtype, heartbeat fields. The ID carries only **category + node_id**. This
   is Extended like ADR-0001 but with **`node_id`** semantics, *not* location — adopted for
   category headroom (incl. `CAT_SENSOR`) and `node_id` room, not "location is the address."
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
- **Category + node_id headroom (Extended IDs), no zero-sum trades** — a 4-bit category gives
  `CAT_SENSOR` and future classes clean slots + priority (with a `CAT_EXTENDED` escape so the
  field never needs widening), and `node_id` has ample room. In-ID per-category fields
  (`button`/`event`, `measurement_type`, a `source_ctrl` tag) are **deferred to the reserved
  bits** until a consumer can hardware-filter on them — not frozen speculatively now.
- **Fits ADR-0003 and ADR-0004's KNX conclusion** — `node_id` = individual (physical)
  address; the central map = function assignment (KNX group/ETS). Fully realises the
  dual-identity split ADR-0004 was circling.
- **No node_id↔room drift** — room/board exist *only* in the map; one node-side coordinate.
- **Sensor-node identification solved** via the printed id (the gap that broke press-to-assign).

### Negative / costs
- **Supersedes ADR-0001 but keeps Extended IDs.** ADR-0001's *location-as-address* Extended
  implementation (PR #6) was reverted (PR #8); this ADR re-adopts Extended IDs with `node_id`
  semantics for different reasons (above). Net firmware path: take main's post-revert v1
  *standard-ID* firmware to **Extended IDs + node_id-only identity**.
- **Extended-ID cost** — ~2–3 extra bytes on the wire per frame (negligible at 125 kbps with
  sparse traffic) and a frozen one-way layout at LIVE. Extended ≠ bigger payload (that is
  CAN FD; the MCP2515 nodes are classic CAN).
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
- **ADR-0004** → revised: `button`/`event` live **in the payload** — the ID's low bits stay
  reserved (no consumer hardware-filters on them yet), so they are not carried in the ID.
  **D3** priority sub-ordering is by `node_id` within a category. KNX-alignment strengthens.
- **ADR-0006** → revised: `CAT_SENSOR` is a first-class **4-bit category**; sensor frames are
  `[CAT_SENSOR][node_id]` with `measurement_type` + value in the **payload**; room derived
  centrally.
- **ADR-0003 / ADR-0005** → unaffected (controller is the central authority either way;
  `node_id` is globally unique, hence segment-agnostic across bridged buses).

## Alternatives considered (the journey)
- **Location-as-address (ADR-0001).** Superseded — its benefit evaporated under centralization.
- **Identical firmware + intrinsic hwid (option 2a).** Rejected — 64-bit hwid blows the
  8-byte payload budget and a truncated/hashed id reintroduces collision math.
- **Progressive temp-id + runtime reassignment (ADR-0002 staging).** Rejected — requires
  persist-over-CAN and write-then-reboot on wall-mounted boards.
- **Standard 11-bit IDs (`[category:2][node_id:9]`).** Considered — and briefly the
  post-revert baseline — but **rejected**: the 2-bit category is already full, so
  `CAT_SENSOR` (ADR-0006) has no slot, and every field is a zero-sum trade against `node_id`.
  Extended IDs end the squeeze for ~2–3 bytes/frame.
- **Flat `node_id` + central map + Extended IDs (this).** Chosen — minimal node state, no
  reassignment, no collisions, category + `node_id` headroom; fits the centralized + KNX
  direction.

## Open items
1. **ID layout: resolved → 29-bit Extended `[category:4][node_id:13][reserved:12]`**
   (Decision §2). Remaining detail: freeze the `category` enum (incl. `CAT_EXTENDED`) in
   `canbus_protocol.h`; the low 12 bits stay **reserved** until a consumer needs them.
2. Define the central-map schema + the controller's commissioning service (list/identify
   nodes, edit the map) and its backup.
3. `node_id` allocation tooling (persistent counter / next-free) + label printing.
4. Implementation: move main's post-revert v1 *standard-ID* firmware to **Extended IDs**
   (`use_extended_id`), 4-bit category incl. `CAT_SENSOR`, `node_id`-only identity (drop
   room/board), per-category low fields; re-key ADR-0006 sensors; build the map + CLI/app.
