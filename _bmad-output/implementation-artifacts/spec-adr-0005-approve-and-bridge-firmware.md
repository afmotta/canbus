---
title: 'Approve ADR-0005 and land the segment-bridge firmware'
type: 'feature'
created: '2026-06-10'
baseline_commit: '95b2ed704d3c0451d8469bfe1432748f41da4df3'
status: 'done'
context:
  - '{project-root}/_bmad-output/project-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/adrs/0005-can-bus-topology-segmented-multi-bus.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture.md'
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** ADR-0005 has both of its decisions made (the bus is segmented; coupling is
software bridges, store-and-forward, 125 kbps everywhere) but is still marked Proposed, and
nothing in the repo implements the bridge role its decision mandates. The architecture
document still presents CAN bus topology as a fully open concern.

**Approach:** Formally accept ADR-0005 using the repo's accepted-ADR metadata pattern, then
implement the implementable slice of the decision: a single-purpose, radios-off,
watchdog-protected store-and-forward bridge firmware in minimal ESPHome (resolving ADR-0005
open item 2 in favor of one toolchain), with the queue/pacing logic as natively tested pure
logic following the `ha_arbitration.h` precedent. Align the architecture topology note.
Physical open items (segment count/cable sketch, per-bridge power, hardware soak test,
pricing) stay open — they need the house, not the repo.

## Boundaries & Constraints

**Always:** Preserve ADR-0005's technical substance; use the accepted-ADR frontmatter
convention from ADR-0003/0007; honor the ADR's mandatory reliability requirements in the
firmware (single-purpose, radios off, watchdog/brownout, fail-safe-silent, conservative
forwarding); keep pure logic ESPHome-free and natively tested; keep the wire protocol
unchanged except for additive constants.

**Ask First:** If implementing the bridge would require breaking changes to
`canbus_protocol.h`; if the bridge needs registry/generator (`nodes.csv` /
`generate_nodes.py`) schema changes; if forward-all proves insufficient and selective
filtering is needed.

**Never:** Do not pick the segment count or invent a zone layout (ADR-0005 open item 1 is
physical); do not mix node/actuator roles into the bridge firmware; do not add WiFi/BT/API
to the bridge; do not introduce loops or any non-tree forwarding.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normal forwarding | Extended frame received on either segment | Frame queued, drained FIFO within the paced cap, retransmitted verbatim on the other segment | N/A |
| Burst | More frames than the drain cap per tick | Queue absorbs up to BRIDGE_QUEUE_MAX; order preserved; TX paced | N/A |
| Queue overflow | Sustained input beyond queue capacity | New frame dropped (drop-newest), counted, WARN logged | ERR_BRIDGE_QUEUE_OVERFLOW latched into heartbeat until reboot |
| Oversize frame | Payload > 8 bytes (non-conformant) | Rejected, counted, never queued | Same latched flag |
| Bridge hang/reset | Watchdog or brownout trips | Panic-reboot; comes up clean; degrades to silent (zone inputs lost), never babbles | Hardware soak test (ADR-0005 open item 5) |
| Bridge health | 30 s tick | Node-format CAT_STATUS heartbeat on the backbone side with uptime + latched flags | Gateway sees a dead bridge as a missing heartbeat |

</frozen-after-approval>

## Code Map

- `_bmad-output/planning-artifacts/adrs/0005-can-bus-topology-segmented-multi-bus.md` -- target ADR: approval metadata, status text, open-item 2 resolution.
- `firmware/bridge/bridge.yaml` -- new bridge firmware (LilyGO T-2CAN: ESP32-S3 TWAI backbone side + MCP2515 zone side; forward-all, radios off, watchdogs, heartbeat, stats).
- `firmware/protocol/bridge_forwarding.h` -- new pure-logic store-and-forward queues, drain pacing, stats, error-flag derivation.
- `firmware/protocol/canbus_protocol.h` -- additive only: `ERR_BRIDGE_QUEUE_OVERFLOW` heartbeat flag.
- `firmware/tests/test_bridge_forwarding.cpp` -- new native test for the forwarding logic.
- `firmware/README.md` -- new "CAN Segment Bridge (ADR-0005)" section.
- `_bmad-output/planning-artifacts/architecture.md` -- topology concern annotated as structurally resolved by ADR-0005.

## Tasks & Acceptance

**Execution:**
- [x] ADR-0005 -- frontmatter `Proposed` → `Accepted` + `acceptedDate: '2026-06-10'`; status section reads as accepted; open item 2 marked resolved (minimal ESPHome).
- [x] `firmware/protocol/bridge_forwarding.h` -- bounded FIFO per direction, drop-newest on overflow, paced drain (BRIDGE_DRAIN_MAX per tick), cumulative stats, latched error-flag helper, static stores.
- [x] `firmware/protocol/canbus_protocol.h` -- add `ERR_BRIDGE_QUEUE_OVERFLOW = 0x04` (additive, pre-LIVE policy).
- [x] `firmware/bridge/bridge.yaml` -- esp32_can (TWAI, backbone) + mcp2515 (zone, with GPIO9 boot reset pulse) per the T-2CAN reference firmware; match-all extended `on_frame` → enqueue, 10 ms drain tick, 30 s backbone heartbeat, 60 s stats log, esp-idf watchdog/brownout sdkconfig, no network components.
- [x] `firmware/tests/test_bridge_forwarding.cpp` -- FIFO/payload fidelity, oversize/overflow rules, drain cap, error-flag latching; passes with `g++ -std=c++17 -Wall -Wextra`.
- [x] `firmware/README.md` + `architecture.md` -- document the bridge and close the topology-method gap in the planning set.

**Acceptance Criteria:**
- Given ADR-0005 is the topology decision record, when its frontmatter and status are reviewed, then it is `Accepted` with date `2026-06-10` and the still-open physical items are explicitly preserved.
- Given the ADR's mandatory reliability requirements, when `bridge.yaml` is reviewed, then each requirement maps to a concrete config element (no radios, watchdog/brownout panic-reboot, single-purpose, paced store-and-forward, observable degradation).
- Given the repo's pure-logic testing convention, when the native tests run, then `test_bridge_forwarding.cpp`, `test_ha_arbitration.cpp`, and `test_protocol.cpp` all pass.
- Given the protocol freeze discipline, when `canbus_protocol.h` is diffed, then the only change is one additive error-flag constant.

## Spec Change Log

- 2026-06-10: Hardware re-targeted from "ESP32 + 2× MCP2515" to the LilyGO T-2CAN per
  Alberto: the board's second CAN port is the ESP32-S3's built-in TWAI controller, not a
  second MCP2515 (source: LilyGO reference firmware,
  <https://github.com/Xinyuan-LilyGO/T-2Can/blob/main/esphome/can.yaml>). TWAI takes the
  backbone side (interrupt-driven RX), MCP2515 the zone side.

## Design Notes

`bridge.yaml` was validated with `esphome config` AND fully compiled with
`esphome compile` (ESPHome 2026.5.3, esp-idf 5.5.4, ESP32-S3 target) — "Successfully
compiled program", no warnings in project code. Three forwarding assumptions were also
verified against the installed ESPHome source: `on_frame` with `can_id: 0` +
`can_id_mask: 0` matches every frame of the configured extended/standard kind
(`canbus.cpp` trigger loop), `esp32_can` runs `TWAI_MODE_NORMAL` (no self-reception, so
forward-all cannot echo), and `mcp2515` returns `ERROR_ALLTXBUSY` once its 3 TX buffers
fill (the drain-pacing rationale). The remaining gate is the open-item-5 hardware soak.
The bridge takes its `node_id` as a substitution rather than a registry change because
`generate_nodes.py` emits a button-node YAML per CSV row; teaching the registry about roles
is deliberately out of scope (Ask First boundary).

## Verification

**Commands:**
- `grep -nE "status: 'Accepted'|acceptedDate" _bmad-output/planning-artifacts/adrs/0005-can-bus-topology-segmented-multi-bus.md` -- expected: both acceptance markers present.
- `g++ -std=c++17 -Wall -Wextra firmware/tests/test_bridge_forwarding.cpp -o /tmp/bridge && /tmp/bridge` -- expected: `test_bridge_forwarding: all assertions passed`.
- `g++ -std=c++17 -Wall -Wextra firmware/tests/test_protocol.cpp -o /tmp/proto && /tmp/proto` -- expected: protocol self-checks still pass with the additive flag.
- `grep -cE "wifi:|api:|ota:" firmware/bridge/bridge.yaml` -- expected: matches only inside comments (radios-off requirement).
- `esphome compile firmware/bridge/bridge.yaml` -- expected: builds clean (validated with ESPHome 2026.5.3).

**Manual checks (if no CLI):**
- Read `bridge.yaml` against ADR-0005's "mandatory reliability requirements" list and confirm a one-to-one mapping.

## Suggested Review Order

**Intent & Acceptance**

- Approved scope and human-owned boundaries.
  [`spec-adr-0005-approve-and-bridge-firmware.md:15`](spec-adr-0005-approve-and-bridge-firmware.md#L15)

**ADR Ratification**

- Acceptance metadata, status text, and the open-item-2 resolution.
  [`0005-can-bus-topology-segmented-multi-bus.md:19`](../planning-artifacts/adrs/0005-can-bus-topology-segmented-multi-bus.md#L19)

**Forwarding Logic**

- Queue sizing/pacing rationale and the drop rules.
  [`bridge_forwarding.h:1`](../../firmware/protocol/bridge_forwarding.h#L1)

- Native coverage of those rules.
  [`test_bridge_forwarding.cpp:1`](../../firmware/tests/test_bridge_forwarding.cpp#L1)

**Bridge Firmware**

- Reliability-requirement mapping in the config header comment, then the two-bus forward path.
  [`bridge.yaml:1`](../../firmware/bridge/bridge.yaml#L1)

**Planning Alignment**

- Topology concern now split into decided method vs open physical sketch.
  [`architecture.md:75`](../planning-artifacts/architecture.md#L75)
