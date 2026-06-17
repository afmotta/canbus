---
title: 'Accept ADR-0011 (health monitoring) + gateway aliveness slice (open item 1)'
type: 'feature'
created: '2026-06-16'
status: 'done'
baseline_commit: 'a983ab15a06ec0470251ff3514aa12615824b8d4'
context:
  - '{project-root}/_bmad-output/project-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/adrs/0011-health-monitoring-degraded-mode-visibility.md'
  - '{project-root}/firmware/protocol/ha_arbitration.h'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** ADR-0011 is `Proposed`. The raw health signals already exist — every node/bridge heartbeats `error_flags` + uptime every 30 s — but the gateway only *logs* them: nothing knows a node went silent, fallback nights are invisible outside serial logs, and HA has no fleet view.

**Approach:** Accept ADR-0011 via the repo's accepted-ADR convention, then implement only **open item 1 — the aliveness slice**: a new pure-logic header `node_health.h` (per-mapped-node `last_seen`, lost-after-90 s, edge detection, online/missing counts) wired into the gateway's existing `CAT_STATUS` handler to fire edge events and publish a few aggregate entities. Defer open items 2–6. No protocol/wire change.

## Boundaries & Constraints

**Always:** Use the accepted-ADR convention (ADR-0007/0010: `status: 'Accepted'` + `acceptedDate` + an `**Accepted (DATE).**` Status paragraph), preserving ADR-0011's substance — the watch hierarchy (nodes ← gateway ← HA ← human), the one-staleness-doctrine (3× cadence = 90 s, shared with ADR-0006), edges-and-aggregates-never-streams, the three alerting classes. `node_health.h` mirrors `ha_arbitration.h`: no ESPHome includes, wraparound-safe unsigned time math, edge/count functions take plain arrays so they are natively testable. Threshold is a YAML substitution. Track **mapped** nodes only. Cite ADR-0011 in every file touched.

**Ask First:** If the slice would require any change to `canbus_protocol.h` payload layout (it must not). If `node_map.h` would need hand-editing (it must not — derive the store index from `node_map_find`).

**Never:** Do not build open items 2–6: no generated HA package / per-node HA entities (ADR-0009 generator owns it), no per-node ESPHome entities on the ESP32 (~6 aggregates only — the rejected alternative), no `segment` column/grouping (blocked on physical topology), no bus-error-counter probing, no Story 5.1 storm rework. Do not stream raw heartbeats to HA. Do not add node-side machinery (nodes stay dumb, ADR-0007). Do not persist watch-state to flash (RAM-only is the accepted cost). Do not hand-edit generated `firmware/nodes/` or `node_map.h`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior |
|----------|--------------|-------------------|
| First heartbeat, clean | mapped node, never seen, `error_flags==0` | `seen=true`, `last_seen` set, NO edge; counted online |
| First heartbeat, with error | mapped, never seen, `error_flags!=0` | error edge fires (carries flags); online |
| Node goes silent | online, `now - last_seen > 90 000 ms` | `node_lost` fires once on the transition; `lost=true`; → missing. Re-check never double-fires |
| Lost node returns | `lost==true`, heartbeat arrives | `node_recovered` fires once; `lost=false`; → online |
| Error flags change | seen, flags differ from last (incl. clearing to 0) | `node_error` fires once carrying new flags. Unchanged flags → no edge (no 30 s spam) |
| Unknown node heartbeats | `node_id` not in map | existing `canbus_node_unknown` only — NOT health-tracked |
| millis() wraparound | `last_seen` near 2^32, `now` wrapped | lost math stays correct (unsigned subtraction) |
| Gateway reboot | store zeroed | online=0 → re-learns within ~30 s (accepted RAM-only cost) |

</frozen-after-approval>

## Code Map

- `_bmad-output/planning-artifacts/adrs/0011-health-monitoring-degraded-mode-visibility.md` -- target ADR to accept (frontmatter + Status + open-items status).
- `_bmad-output/planning-artifacts/adrs/0007-flat-node-id-with-central-meaning-map.md` -- accepted-ADR convention exemplar.
- `firmware/protocol/ha_arbitration.h` -- pattern to mirror (store() idiom, wraparound math, native-testable functions).
- `firmware/protocol/node_health.h` -- **NEW** pure-logic aliveness header.
- `firmware/protocol/node_map.h` -- GENERATED; `node_health.h` includes it for `NODE_MAP`/`NODE_MAP_SIZE`. Inspect-only.
- `firmware/protocol/canbus_protocol.h` -- existing `payload_errors`/`ERR_*` decoders the gateway already uses; no change.
- `firmware/gateway/gateway.yaml` -- include the header; extend `CAT_STATUS` handler; sweep interval; aggregate entities; fallback counter.
- `firmware/tests/test_node_health.cpp` -- **NEW** native test (mirrors `test_ha_arbitration.cpp`).
- `firmware/README.md` -- add the native-test one-liner + brief note on the new entities/events.
- `_bmad-output/project-context.md` -- one bullet on the aliveness header + string event fields.
- `_bmad-output/implementation-artifacts/deferred-work.md` -- log open items 2–6.

## Tasks & Acceptance

**Execution:**
- [x] `firmware/protocol/node_health.h` -- NEW: `struct NodeHealth {uint32_t last_seen_ms; bool seen; bool lost; uint8_t error_flags;}`, `HEALTH_EDGE_RECOVERED/ERROR` bitflags, `health_on_heartbeat()` (returns edge mask, latches seen/last_seen/flags), `health_check_lost()` (once-only `seen&&!lost`→`lost` past `timeout_ms`), `health_is_missing()`, `health_nodes_online()`, `node_health_index()` (via `node_map_find`), `node_health_store()` (static array sized by `NODE_MAP_SIZE`). Wraparound-safe unsigned math, no ESPHome includes -- the natively-testable aliveness core (ADR-0011 §1).
- [x] `firmware/gateway/gateway.yaml` -- include `node_health.h`; add `node_lost_timeout_ms: "90000"` substitution + `fallback_events` global; in the `CAT_STATUS` handler call `health_on_heartbeat` for mapped nodes and fire `esphome.canbus_node_recovered` / `esphome.canbus_node_error`; add a 5 s sweep `interval` firing `esphome.canbus_node_lost` on transitions and publishing `nodes_online` / `fallback_events_count` / `nodes_missing`; publish constant `nodes_total` at `on_boot`; declare the four template sensors; increment `fallback_events` at both existing fallback log points -- wires the slice to HA as edges + aggregates (ADR-0011 §2–§4).
- [x] `firmware/tests/test_node_health.cpp` -- NEW native test covering every I/O Matrix row (first-clean/first-error, lost-once + idempotent, recovered, error-change incl. clear-to-0, online/missing counts, `node_health_index` mapped/unmapped, wraparound) -- proves the pure logic.
- [x] `firmware/README.md` -- add the `g++ ... test_node_health.cpp` one-liner alongside the other native tests + a short bullet on the new aliveness entities/events.
- [x] `_bmad-output/planning-artifacts/adrs/0011-health-monitoring-degraded-mode-visibility.md` -- flip frontmatter to `Accepted` + `acceptedDate: '2026-06-16'`, rewrite Status to the `**Accepted (2026-06-16).**` form (preserve substance + watch hierarchy + staleness doctrine), mark open item 1 implemented and 2–6 deferred.
- [x] `_bmad-output/project-context.md` -- add one Critical-rules bullet: aliveness lives in `node_health.h` (one staleness doctrine, 3× cadence, 90 s) and the new `canbus_node_lost/recovered/error` event data fields are strings.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- append a "Deferred from: ADR-0011 acceptance + aliveness slice (2026-06-16)" section logging open items 2 (generated HA package → ADR-0009 generator), 3 (bus-error counters → not load-bearing), 4 (Story 5.1 storm → security class), 5 (`segment` column → physical-topology ADR), 6 (threshold tuning → bench session); note item 1 resolved here.

**Acceptance Criteria:**
- Given ADR-0011 is the health-monitoring record, when frontmatter/Status are reviewed, then it is `Accepted` with `acceptedDate: '2026-06-16'`, reads as ratified (substance + watch hierarchy + one-staleness-doctrine preserved), open item 1 marked implemented, 2–6 marked deferred.
- Given `node_health.h` is pure logic, when `test_node_health.cpp` is compiled and run, then all assertions pass and the header compiles standalone (`g++ -std=c++17`, no ESPHome dependency).
- Given the gateway compiles, when `esphome config firmware/gateway/gateway.yaml` runs, then it validates with the header included, the four new entities present, and button/heartbeat forwarding behavior unchanged.
- Given the ESP32 carries only aggregates (the rejected per-node alternative), when its entities are counted, then there are ~6 health/diagnostic entities — independent of fleet size — and no raw heartbeat stream is forwarded.
- Given open items remain, when `deferred-work.md` is read, then 2–6 are logged with owners and item 1 is recorded as resolved here.

## Spec Change Log

## Design Notes

Mirrors `ha_arbitration.h`: pure functions take caller-owned arrays (testable with stack arrays); `node_health_store()` returns the one static array (ESPHome globals can't hold the custom struct — storage is declared before user includes); all time math is unsigned subtraction. The store is sized by `NODE_MAP_SIZE` and indexed by map position (`node_health_index` = `node_map_find(id) - NODE_MAP`), staying in lock-step with the compiled map without touching the generated file.

```cpp
NodeHealth h{};                                   // never seen
health_on_heartbeat(h, 1000, ERR_NONE);           // -> HEALTH_EDGE_NONE (first clean sighting)
health_check_lost(h, 1000 + 90001, 90000);        // -> true  (node_lost, once)
health_check_lost(h, 1000 + 95000, 90000);        // -> false (already lost, idempotent)
health_on_heartbeat(h, 200000, ERR_NONE);         // -> HEALTH_EDGE_RECOVERED
health_on_heartbeat(h, 230000, ERR_CAN_BUS_OFF);  // -> HEALTH_EDGE_ERROR (flags changed)
```

`nodes_total` is compile-time `NODE_MAP_SIZE` (published once at boot). `nodes_online` = `seen && !lost`; a mapped-but-never-seen node is *missing* (in `nodes_missing`) but never fires a spurious `node_lost` — "lost" means was-present-now-gone, distinct from never-commissioned. Aggregates re-publish every 5 s sweep, so they survive the HA blind window by construction (ADR-0011 §2). The HA-side per-node entities, alert automations, and reconnect report are NOT here — they ride the ADR-0009 generator extension (open item 2).

## Verification

**Commands:**
- `g++ -std=c++17 -Wall -Wextra firmware/tests/test_node_health.cpp -o /tmp/health && /tmp/health` -- expected: `test_node_health: all assertions passed`.
- `g++ -std=c++17 -Wall -Wextra -fsyntax-only firmware/protocol/node_health.h` -- expected: clean.
- `esphome config firmware/gateway/gateway.yaml >/dev/null && echo CONFIG_OK` -- expected: `CONFIG_OK` (if esphome available).
- `grep -nE "status: 'Accepted'|acceptedDate" _bmad-output/planning-artifacts/adrs/0011-health-monitoring-degraded-mode-visibility.md` -- expected: both markers present.
- `grep -ln "ADR-0011" firmware/protocol/node_health.h firmware/gateway/gateway.yaml firmware/tests/test_node_health.cpp _bmad-output/project-context.md _bmad-output/implementation-artifacts/deferred-work.md` -- expected: each file cites ADR-0011.

**Manual checks (if no CLI):**
- If `esphome` is unavailable: confirm `gateway.yaml` includes `../protocol/node_health.h`, the `CAT_STATUS` handler calls `health_on_heartbeat` for mapped nodes, the sweep `interval` fires `esphome.canbus_node_lost`, and the four template sensors (`nodes_online`, `nodes_total`, `fallback_events_count`, `nodes_missing`) are declared.

## Suggested Review Order

**The decision (start here)**

- ADR ratified: aliveness on the gateway, edges + aggregates, one staleness doctrine; open item 1 marked implemented, 2–6 deferred.
  [`0011-...md:25`](../planning-artifacts/adrs/0011-health-monitoring-degraded-mode-visibility.md#L25)

**The aliveness core (pure logic)**

- The watch-state struct + how loss/recovery/error are modelled — the design intent in one type.
  [`node_health.h:25`](../../firmware/protocol/node_health.h#L25)
- The key correctness rule: RECOVERED fires only for an *announced* loss, so edges stay paired (no orphan recovered, no dropped lost).
  [`node_health.h:50`](../../firmware/protocol/node_health.h#L50)
- The once-only silence transition (wraparound-safe, never seen → never "lost").
  [`node_health.h:68`](../../firmware/protocol/node_health.h#L68)
- One declarative `node_lost` per sweep tick without dropping simultaneous losses.
  [`node_health.h:97`](../../firmware/protocol/node_health.h#L97)

**Gateway wiring (the header/YAML seam)**

- Heartbeat handler fires `node_recovered` / `node_error` edges for mapped nodes (staged via a global, x in scope for re-decode).
  [`gateway.yaml:368`](../../firmware/gateway/gateway.yaml#L368)
- Sweep interval: `node_lost` edge + re-publish the aggregates (survives the HA blind window).
  [`gateway.yaml:248`](../../firmware/gateway/gateway.yaml#L248)
- The ~6 aggregate entities — fleet-size-independent, no per-node ESP32 entities.
  [`gateway.yaml:212`](../../firmware/gateway/gateway.yaml#L212)
- Threshold as a tunable substitution (ADR open item 6).
  [`gateway.yaml:26`](../../firmware/gateway/gateway.yaml#L26)

**Supporting (tests + tracking)**

- Native test, incl. the orphan-prevention + combined-edge cases the review added.
  [`test_node_health.cpp:38`](../../firmware/tests/test_node_health.cpp#L38)
- Open items 2–6 logged with owners.
  [`deferred-work.md:10`](deferred-work.md#L10)
