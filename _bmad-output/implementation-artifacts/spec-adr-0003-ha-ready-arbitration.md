---
title: 'ADR-0003 acceptance + ha_ready arbitration prototype on gateway'
type: 'feature'
created: '2026-06-10'
status: 'done'
baseline_commit: '942a8615853bfdb2044317682028c7049f3aec52'
context:
  - '{project-root}/_bmad-output/planning-artifacts/adrs/0003-centralized-single-controller-with-onboard-fallback.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** ADR-0003 (centralized controller with on-board fallback) is still `Proposed`, and its core arbitration mechanism — `ha_ready` gating with readiness heartbeat, manifest-hash check, and per-event ACK/fallback timeout — has never run anywhere, so open item 2 (timeout values) cannot be resolved empirically.

**Approach:** Mark ADR-0003 Accepted, then prototype the full readiness/arbitration machinery on the current ESP32-S3 gateway: HA-side readiness heartbeat consumed via Native API services, `ha_ready` state computation, and per-button-event ACK tracking with timeout. Fallback actions only **log** (no relays exist yet); the binding manifest is stubbed by a fixed placeholder hash substitution.

## Boundaries & Constraints

**Always:**
- Arbitration is HA ↔ gateway over the Native API only — zero CAN protocol changes, zero node firmware changes.
- All `homeassistant.event` data values are strings (`event_id` included).
- Keep the shipped CAT_INPUT handler patterns: `if:/condition:` payload guards, per-field `!lambda` re-decode from `x` (no globals for event data).
- Time comparisons use unsigned `uint32_t` subtraction so `millis()` wraparound cannot wedge `ha_ready` or pending-ACK expiry.
- New C++ helpers go in a header following `canbus_protocol.h` conventions: `inline`, `UPPER_SNAKE_CASE` constants, `snake_case` functions, pure logic (natively testable, no ESPHome includes).
- Timeouts are `substitutions:` (tunable without code edits — that is how open item 2 gets resolved on hardware).

**Ask First:**
- Adding any new CAN frame, payload type, or `canbus_protocol.h` change.
- Renaming or removing existing `esphome.canbus_button` event fields.

**Never:**
- No relay/output driving of any kind (no PCA9554, no Modbus) — fallback is observable via logs and the `ha_ready` sensor only.
- No binding manifest format or generator (separate deferred slice) — the manifest hash is a placeholder substitution.
- No button-state/bitmask fields in frames or HA payloads.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Ready + ACK in time | `ha_ready` true; button event; HA ACKs `event_id` < `ack_timeout_ms` | HA event fired with `event_id`; pending entry cleared; no fallback log | N/A |
| Ready + ACK missed | `ha_ready` true; button event; no ACK before deadline | WARN log `FALLBACK (ack timeout)` with node/button/event/event_id; entry removed | single fire per event_id |
| Not ready | heartbeat stale > TTL, or hash mismatch, or API disconnected; button event | WARN log `FALLBACK (ha not ready)` immediately; no HA event, no pending entry | N/A |
| Hash mismatch heartbeat | `ha_readiness_heartbeat` with hash ≠ `manifest_hash` | heartbeat timestamp updates, `ha_hash_ok` false → `ha_ready` false | WARN once per change |
| Unknown ACK | `ha_ack_event` with unmatched `event_id` | ignored | DEBUG log |
| millis() wrap | `last_hb_ms` near `UINT32_MAX`, now wrapped | TTL/deadline math still correct | unsigned arithmetic |

</frozen-after-approval>

## Code Map

- `_bmad-output/planning-artifacts/adrs/0003-centralized-single-controller-with-onboard-fallback.md` -- status flip + open-items reconciliation
- `firmware/protocol/canbus_protocol.h` -- conventions reference only; do not modify
- `firmware/protocol/ha_arbitration.h` -- NEW: pure-logic arbitration helpers
- `firmware/gateway/gateway.yaml` -- input-only bridge; gains services, globals, ha_ready sensor, ACK sweep, event_id in CAT_INPUT handler
- `firmware/gateway/ha_arbitration_automations.yaml` -- NEW: documented HA-side example (heartbeat + ACK automations)
- `firmware/tests/test_protocol.cpp` -- native g++ test pattern to mirror
- `firmware/README.md` -- document the prototype + test command

## Tasks & Acceptance

**Execution:**
- [x] `_bmad-output/planning-artifacts/adrs/0003-...md` -- frontmatter `status: 'Accepted'`, `acceptedDate: '2026-06-10'`; rewrite Status section; mark open item 4 resolved (PoC command hooks already removed by the ADR-0007 protocol rewrite); note bindings key on `(node_id, button)` per ADR-0007 §6 -- the acceptance half of the intent
- [x] `firmware/protocol/ha_arbitration.h` -- NEW: `struct PendingAck {event_id, deadline_ms, node_id, button, event_type}`; `ha_ready(api_connected, hash_ok, hb_seen, last_hb_ms, now_ms, ttl_ms)`; `pending_add / pending_ack / pending_expire` over `std::vector<PendingAck>`; the list itself is owned here via `pending_acks_store()` (ESPHome `globals:` cannot carry a custom struct type — storage is declared before user includes in generated main.cpp) -- pure logic so the timeout machinery is unit-testable off-target
- [x] `firmware/gateway/gateway.yaml` -- include new header; substitutions `manifest_hash: "dev-unbound"`, `ha_heartbeat_ttl_ms: "15000"`, `ack_timeout_ms: "500"`; globals (`last_ha_hb_ms`, `ha_hb_seen`, `ha_hash_ok`, `next_event_id`); `api: services:` `ha_readiness_heartbeat(manifest_hash: string)` and `ha_ack_event(event_id: int)`; template binary_sensor `ha_ready_sensor` "HA Ready" (diagnostic); `interval:` 250ms pending-expiry sweep; CAT_INPUT recognized-event branch gains the ready/not-ready arbitration per the I/O matrix -- the prototype itself
- [x] `firmware/gateway/ha_arbitration_automations.yaml` -- NEW: copy-into-HA example automations: 5s readiness heartbeat (passing the manifest hash) and on-event ACK calling `ha_ack_event` -- the HA half of the loop, documentation-grade
- [x] `firmware/tests/test_ha_arbitration.cpp` -- NEW: native test mirroring `test_protocol.cpp` covering the full I/O matrix incl. wraparound -- guards the pure-logic core
- [x] `firmware/README.md` -- short section: arbitration prototype, substitutions to tune (open item 2), test command -- discoverability

**Acceptance Criteria:**
- Given the repo after implementation, when ADR-0003 is read, then status is Accepted (2026-06-10) and open item 4 is recorded as already resolved.
- Given HA calls `ha_readiness_heartbeat` with the matching hash every 5s, when heartbeats stop for longer than `ha_heartbeat_ttl_ms`, then the `ha_ready` binary sensor turns off and subsequent button events log `FALLBACK (ha not ready)` instead of firing HA events.
- Given `ha_ready` is on, when a button event fires and no ACK arrives within `ack_timeout_ms`, then exactly one WARN fallback log is emitted for that `event_id`.

## Design Notes

`ha_ready` is computed, never stored as authority: `api_connected && hash_ok && hb_seen && (now - last_hb) <= ttl`. `hb_seen` exists because `last_hb_ms == 0` is a valid timestamp, not a sentinel (same reasoning as node_id 0). The pending list is a `std::vector<PendingAck>` global — home-scale event rates make O(n) sweep at 250ms trivially cheap. `event_id` is a gateway-local monotonic `uint32_t`, not a protocol field.

## Verification

**Commands:**
- `g++ -std=c++17 -Wall -Wextra firmware/tests/test_ha_arbitration.cpp -o /tmp/arb && /tmp/arb` -- expected: exits 0, all asserts pass
- `g++ -std=c++17 -Wall -Wextra firmware/tests/test_protocol.cpp -o /tmp/proto && /tmp/proto` -- expected: still passes (no protocol change)
- `cd firmware/gateway && esphome compile gateway.yaml` -- expected: compiles clean (ESPHome 2026.5.0 known-good)

**Manual checks (if no CLI):**
- Bench (later, Epic-style): toggle the HA heartbeat automation off and verify `ha_ready` drops within TTL and fallback logs appear on button press.

## Suggested Review Order

**Design intent: the ha_ready gate**

- The whole arbitration in one formula — computed, never stored as authority.
  [`ha_arbitration.h:50`](../../firmware/protocol/ha_arbitration.h#L50)
- Where the gate forks button events: forward-with-event_id vs immediate log-only fallback.
  [`gateway.yaml:193`](../../firmware/gateway/gateway.yaml#L193)
- ADR-0003 flipped to Accepted; what changed between proposal and acceptance.
  [`0003-...md:22`](../planning-artifacts/adrs/0003-centralized-single-controller-with-onboard-fallback.md#L22)

**Readiness inputs (heartbeat, hash, disconnect)**

- HA proves liveness + manifest hash; substitution confined to one literal, first-mismatch WARN.
  [`gateway.yaml:61`](../../firmware/gateway/gateway.yaml#L61)
- Disconnect conservatively revokes readiness — stale-hash window across HA restarts closed.
  [`gateway.yaml:107`](../../firmware/gateway/gateway.yaml#L107)
- Diagnostic HA Ready sensor; is_connected() is any-client, heartbeat TTL is the HA term.
  [`gateway.yaml:139`](../../firmware/gateway/gateway.yaml#L139)

**ACK lifecycle + tuning instrumentation**

- ACK service: rtt on success, LATE-ACK WARN (the double-action window datum), unknown at DEBUG.
  [`gateway.yaml:86`](../../firmware/gateway/gateway.yaml#L86)
- 250ms sweep: single-fire fallback with measured `waited=`; expired ring feeds late-ACK detection.
  [`gateway.yaml:152`](../../firmware/gateway/gateway.yaml#L152)
- Pending/expired stores live in the header — ESPHome globals can't carry custom structs.
  [`ha_arbitration.h:77`](../../firmware/protocol/ha_arbitration.h#L77)
- Wraparound-safe deadline check and the bounded add/ack/expire machinery.
  [`ha_arbitration.h:59`](../../firmware/protocol/ha_arbitration.h#L59)

**HA-side counterpart**

- 5s heartbeat carrying the manifest hash (stop it to exercise the degraded path).
  [`ha_arbitration_automations.yaml:23`](../../firmware/gateway/ha_arbitration_automations.yaml#L23)
- Parallel ACK automation; `int(-1)` default so malformed events never ACK a real entry.
  [`ha_arbitration_automations.yaml:38`](../../firmware/gateway/ha_arbitration_automations.yaml#L38)

**Peripherals**

- Native test: truth table, both wraparound cases, cap/ring bounds, single-fire expiry.
  [`test_ha_arbitration.cpp:13`](../../firmware/tests/test_ha_arbitration.cpp#L13)
- Operator docs: tuning substitutions and which log lines carry the open-item-2 data.
  [`README.md:104`](../../firmware/README.md#L104)
- Tunables in one place; `manifest_hash` placeholder until the binding-manifest slice.
  [`gateway.yaml:20`](../../firmware/gateway/gateway.yaml#L20)
- Review deferrals: double-action revocation (ADR-level), CI for native tests, root .gitignore.
  [`deferred-work.md:1`](deferred-work.md#L1)
