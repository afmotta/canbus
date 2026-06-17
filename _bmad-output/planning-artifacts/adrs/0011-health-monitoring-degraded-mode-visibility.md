---
adr: 0011
title: 'Health monitoring & degraded-mode visibility: gateway-resident aliveness, edge events to HA, layered alerting'
status: 'Accepted'
date: '2026-06-11'
acceptedDate: '2026-06-16'
deciders: ['Alberto']
author: 'Winston (System Architect)'
dependsOn:
  - 'ADR-0003: Centralized single-controller (ha_ready arbitration; fallback mode is the state to surface)'
  - 'ADR-0005: Segmented topology (bridges heartbeat as nodes; segment-loss discrimination)'
  - 'ADR-0009: Git as system of record (map drives the expected fleet; HA package generation)'
  - 'ADR-0010: Security posture (unknown-node, vanished-node, storm are security signals)'
relatedDocuments:
  - _bmad-output/planning-artifacts/adrs/0006-sensor-data-transport-over-can.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/implementation-artifacts/5-1-gateway-command-reliability.md
  - firmware/protocol/canbus_protocol.h
  - firmware/protocol/node_map.h
  - firmware/gateway/gateway.yaml
---

# ADR-0011: Health monitoring & degraded-mode visibility

## Status

**Accepted (2026-06-16) — aliveness slice implemented.** Closes the oldest deferred item in
the project ("node health dashboard and aliveness alerting" — deferred in architecture.md on
2026-05-31 and unowned since), now broadened by what shipped in between: bridges that
heartbeat with a latched overflow flag (ADR-0005), an `ha_ready` arbitration whose fallback
mode is invisible outside the logs (ADR-0003), and ADR-0010's hand-off of
unknown-node/vanished-node/storm as **security** signals. The raw signals all exist; this ADR
decides who watches them, where aliveness state lives, and how degraded operation reaches a
human. The stance is ratified: aliveness lives on the gateway, HA gets edges and aggregates
rather than streams, every layer is watched by the layer above it (nodes ← gateway ← HA ←
human), and one staleness doctrine (3× cadence = 90 s, shared with ADR-0006) governs nodes,
bridges, and sensor readings alike. **Open item 1 — the aliveness slice — is implemented**:
`protocol/node_health.h` (pure-logic per-node watch state + edge detection, natively tested in
`tests/test_node_health.cpp`) wired into the gateway's `CAT_STATUS` handler, firing the edge
events (`canbus_node_lost` / `_recovered` / `_error`) and publishing the aggregate entities
(`nodes_online` / `nodes_total` / `fallback_events_count` / `nodes_missing`, alongside the
existing `ha_ready`). The remaining open items (2 generated HA package, 3 bus-error counters,
4 Story 5.1 storm routing, 5 `segment` column, 6 threshold tuning) are deferred to their named
owners.

## Context

What already exists, per the current firmware:

- **Heartbeats**: every node and bridge emits `CAT_STATUS` every 30 s carrying
  `error_flags` (`ERR_CAN_TX_FAIL`, `ERR_CAN_BUS_OFF`, `ERR_BRIDGE_QUEUE_OVERFLOW`) and
  uptime. The gateway *logs* them (WARN on errors) and forwards nothing.
- **`ha_ready`** is computed and exposed as one binary sensor; fallback events are
  log-only. Whether the house spent last night in fallback is currently discoverable only
  by reading serial logs.
- **`esphome.canbus_node_unknown`** fires for unmapped node_ids (commissioning discovery —
  and per ADR-0010, the foreign-device alarm).
- **Storm/fault surfacing and command-failure events** are designed in story 5.1
  (ready-for-dev, queued after Epic 4).

Two structural facts shape the design. First, **the gateway is the only component that
can know a node is missing**: it holds the compiled map (the expected fleet, ADR-0009)
and hears every frame; HA cannot notice the silence of a device it has never heard from
— and is itself the component allowed to be down. Second, **the moment that most needs
surfacing — fallback mode — is precisely the moment HA cannot display anything**, so the
design must accumulate state through the blind window and report on reconnection, not
stream and hope.

## Decision

Six parts. The stance in one line: **aliveness lives on the gateway, HA gets edges and
aggregates rather than streams, every layer is watched by the layer above it, and the
monitoring layer is also the security sensor (ADR-0010).**

### 1. Aliveness authority is the gateway

The gateway tracks `last_seen` per **mapped** node (a static array sized by
`NODE_MAP_SIZE`, wraparound-safe `uint32_t` time math, pure-logic header alongside
`ha_arbitration.h` so it is natively testable). A node is **lost** after **3 missed
heartbeats (90 s)** — deliberately the same 3×-cadence rule ADR-0006 set for sensor
staleness; one staleness doctrine, not two. Bridges need no special machinery: they
heartbeat as ordinary nodes (ADR-0005), so bridge death and bridge degradation
(`ERR_BRIDGE_QUEUE_OVERFLOW`) ride the same path. Sensor-reading staleness stays
consumer-side (the HVAC controller's 90 s rule, ADR-0006) — not duplicated here.

### 2. Edges and aggregates to HA — never streams

A whole-house fleet emits ~3 heartbeats/s; forwarding them as HA events would bloat the
recorder with non-information. Instead:

- **Edge events** (fired on transition only): `esphome.canbus_node_lost`,
  `esphome.canbus_node_recovered`, `esphome.canbus_node_error` (error_flags changed,
  carrying the flags), plus the existing `canbus_node_unknown` and story 5.1's
  `canbus_command_failed` / storm fault when they land.
- **Aggregate entities** (native ESPHome sensors on the gateway): `nodes_online` /
  `nodes_total`, `fallback_events_count`, the existing `ha_ready` binary sensor, and a
  `nodes_missing` text sensor (names from the compiled map). Entities — not events —
  because ESPHome republishes entity state on (re)connection: **aggregates survive the
  blind window by construction.**

Per-node HA entities are materialized HA-side from the edge events + `map.json`, by the
generated HA package (this joins ADR-0009's pipeline, same artifact). The ESP32 carries
~6 entities, not ~100.

### 3. Degraded-mode visibility: accumulate through the blind window

- While HA is away, the gateway counts fallback firings and tracks losses as normal; on
  reconnection the aggregates re-publish and a generated HA automation reports: *"ha_ready
  was false for N minutes; M events handled by local fallback; nodes lost: …"*. The house
  may run degraded; it may not run degraded **silently**.
- **Controller-down is HA's job**: the gateway device going unavailable in HA *is* the
  alarm (native ESPHome-integration behavior + one generated alert automation). No
  self-reporting machinery on the gateway for its own death — the layer above watches it.
- The watch hierarchy is explicit: **nodes ← gateway ← HA ← human.** Each layer monitors
  only the layer below; no layer monitors itself; the human is alerted by HA and only HA.
  (HA's own uptime is the household IT layer — out of scope, consistent with ADR-0010.)

### 4. Alerting policy: three classes

| Class | Signals | Policy |
|---|---|---|
| **Security** (ADR-0010 §6) | `node_unknown`, node vanished without explanation, frame storm | Immediate notification |
| **Degraded-mode** | `ha_ready` transitions, fallback events on reconnect report, controller unavailable, bridge lost | Immediate notification |
| **Maintenance** | single node lost/recovered, error flags, bridge overflow flag | Dashboard + daily digest; escalate to notification only if persisting (e.g. >1 h) |

A *bridge* loss is degraded-mode, not maintenance, because it silently takes a whole
segment's future events with it. The class boundaries are the decision; thresholds are
tunable substitutions like the arbitration timeouts.

### 5. Segment-aware loss discrimination — deferred, hook reserved

"Twelve nodes lost at once" and "bridge lost + its twelve nodes" should alert as *one
segment fault*, not thirteen alarms. That needs the map to know which segment a node is
on — a `segment` column that cannot be filled until the physical topology exists
(queue #2, post-tubes). Decided now: the column lands in `nodes.csv` **when segments
materialize** (additive, per ADR-0009's migration pattern); until then the single-bus
deployment needs no grouping. The alert-storm risk is accepted for the PoC interim.

### 6. The monitoring layer is the security layer

Restating ADR-0010 §6 as implementation fact: the Security class in §4 *is* the
intrusion-visibility surface — same events, same plumbing, stricter alerting. No separate
security monitoring exists or is built.

## Consequences

### Positive

- **Closes the loop on three ADRs**: ADR-0003's fallback becomes observable, ADR-0005's
  dead-bridge risk becomes an immediate alert, ADR-0010's detection-over-prevention gets
  its concrete mechanism.
- **Cheap on every axis** — one pure-logic header + a handful of entities on the gateway;
  HA-side complexity is generated, not hand-maintained; no new devices, no new protocol
  (the heartbeat already carries everything needed).
- **Testable where it matters** — staleness/edge logic is native-testable like
  `ha_arbitration.h`; thresholds are substitutions, tunable on hardware.
- **One staleness doctrine** (3× cadence) across nodes, bridges, and sensor readings.

### Negative / costs

- **The gateway's watch-state is RAM-only** — a gateway reboot zeroes counters and
  re-learns last_seen within one heartbeat period (~30 s of "everything just recovered").
  Accepted: persistence would add flash-wear machinery for cosmetic continuity.
- **Blind-window *detail* is bounded** — counts survive reconnection; per-event
  forensics of what fallback did while HA was away live only in serial logs. Accepted at
  house scale (the count is the actionable datum).
- **Alert fatigue is a tuning risk** — mitigated by the three-class policy and digest
  defaults, but thresholds will need the same empirical pass as the arbitration timeouts.
- **Until segments exist, a segment-wide fault alarms per-node** (§5 accepted interim).

## Alternatives considered

- **HA-resident aliveness (forward all heartbeats as events; HA templates track
  staleness).** Rejected: ~3 events/s of recorder noise; HA cannot see silence while
  down (precisely the degraded window that matters most); puts fallback-mode bookkeeping
  in the component whose absence defines fallback mode.
- **Per-node entities on the gateway (~100 ESPHome binary sensors).** Rejected: entity
  bloat on the ESP32 and in HA's registry for state HA can derive from edges + the
  generated package; also couples gateway firmware size to fleet size — recompile per
  commissioning is fine (Phase 1), but RAM/entity scaling shouldn't be.
- **A dedicated watchdog/monitoring device on the bus.** Rejected: new hardware and a
  new firmware to keep honest, duplicating what the gateway already hears; violates
  "boring"; the gateway-down case is already covered by HA natively.
- **Node-side mitigation (nodes self-announce failures beyond the error flags).**
  Rejected: nodes stay dumb (ADR-0007); the existing flags + silence are sufficient
  signal at the cadence chosen.

## Open items

1. ~~**Implement the aliveness slice**: `node_health.h` pure logic + gateway integration
   (edge events, aggregate entities), native tests, thresholds as substitutions.~~
   **Implemented 2026-06-16** (`protocol/node_health.h`, `tests/test_node_health.cpp`,
   `firmware/gateway/gateway.yaml`; `node_lost_timeout_ms` substitution).
2. **Generated HA package**: per-node status entities from edge events + `map.json`,
   the three alert classes, the reconnect report automation — lands with/after the
   ADR-0009 generator extension (same artifact family).
3. **TWAI/MCP2515 bus-error counters**: investigate what ESPHome's `esp32_can` exposes
   (error counters would enrich the Maintenance class); not load-bearing.
4. **Story 5.1 alignment**: when storm surfacing lands, route its fault event into the
   Security class (it predates the class taxonomy).
5. **`segment` column** in `nodes.csv` + grouping logic — blocked on physical topology
   (queue #2), per §5.
6. **Threshold tuning pass** on bench/real deployment alongside the arbitration timeout
   tuning (same empirical session).

## Notes

Completes the observability arc: NFR-8 made the gateway's *pipeline* loggable, story 5.1
makes *commands and storms* observable, this ADR makes the *fleet and the degraded mode*
observable. Leans on ADR-0009 twice (the map defines "expected", the generator builds the
HA side) — accepting ADR-0009 first is the natural order. With this, gap #5 closes; the
remaining queue is #6 (node fault semantics — small, partly subsumed: `ERR_CAN_BUS_OFF`
reporting exists, but node bus-off *recovery policy* and the stale-TX question remain)
and the parked #2 (physical/electrical, post-tubes).
