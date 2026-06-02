# Story 3.3: Gateway CAT_STATUS handler — heartbeat logging

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a developer,
I want the gateway's `on_frame` handler for CAT_STATUS frames to log heartbeat receipt to the ESPHome serial output,
so that node aliveness is observable from the gateway without requiring HA access.

## ⚠️ Critical Context — READ FIRST

The CAT_STATUS handler **already exists and is substantially complete** in [firmware/gateway.yaml](../../firmware/gateway.yaml#L104-L123). This story is **verification + one small log-completeness hardening + compile gate** — not greenfield work.

**Approach (consistent with Story 3.2, decided by Alberto 2026-06-02):** keep the `if:` / `condition:` guard pattern (clean action lambda, no redundant re-checks). Do **not** refactor to a single-lambda form with the guard inlined as the first statement. The project's documented `on_frame` guard preference is `if:/condition:` for payload validity. [Source: memory esphome_on_frame_guard; architecture.md:256-273]

**No HA event is fired for heartbeats in the PoC — logging only.** [Source: epics.md:346; architecture.md:179-181]

**Byte positions:** the epic AC text was corrected to match `canbus_protocol.h` (the single source of truth): uptime=x[2], errors=x[3], room=x[4], board=x[5]. Use the named `payload_*` helpers — never hand-index. [Source: epics.md:345 (corrected); canbus_protocol.h:113-117]

## Acceptance Criteria

1. **AC1 — Guard before any payload access:** For the CAT_STATUS entry (`can_id: 0x600`, `can_id_mask: 0x600`), the size guard `if (x.size() < CAN_FRAME_SIZE) return false;` is the **first check** in the `if:` `condition:` lambda, before any byte is indexed (NFR-2). Exact bound — no `x.empty()`, no magic `8`. [Source: epics.md:344; architecture.md:256-273; memory esphome_on_frame_guard]

2. **AC2 — Full decode logged:** For a valid frame, the handler logs at minimum **uptime hours, error flags, room, and board**, decoded via the named helpers (`payload_uptime` = x[2], `payload_errors` = x[3], `payload_heartbeat_room` = x[4], `payload_heartbeat_board` = x[5]). [Source: epics.md:345 (corrected); canbus_protocol.h:113-117]

3. **AC3 — Log only, no HA event:** No `esphome.canbus_heartbeat` (or any) HA event is fired from this handler — logging only in the PoC (FR-6.2). [Source: epics.md:346; architecture.md:179-181]

4. **AC4 — Distinct, decode-confirming message on every heartbeat:** The log message includes the decoded field values (not a static "heartbeat received"), and the **error byte is surfaced on the normal (non-error) path too**, so AC2 holds for every heartbeat — not only error heartbeats. [Source: epics.md:347]

5. **AC5 — Protocol constants only:** Decoding and the error comparison use named helpers/constants from `canbus_protocol.h` (including `ERR_NONE`). No raw indices, hex, or magic numbers in the YAML lambda. [Source: architecture.md:276-301; project-context.md]

6. **AC6 — Compile gate (both handlers):** `esphome compile firmware/gateway.yaml` completes successfully on ESPHome 2026.5.0 with **both** the CAT_INPUT (Story 3.2) and CAT_STATUS handlers present. [Source: epics.md:348; architecture.md:210-212]

## Tasks / Subtasks

- [ ] **Task 1: Verify guard, decode, and no-HA-event** (AC: 1,3,5)
  - [ ] 1.1: Confirm the `if:` `condition:` lambda's first statement is `if (x.size() < CAN_FRAME_SIZE) return false;` before any byte access (AC1). Current: `if (x.size() < CAN_FRAME_SIZE) return false; return x[0] == PROTO_V1;` — verify unchanged/correct. [firmware/gateway.yaml:110]
  - [ ] 1.2: Confirm decode uses `payload_uptime`, `payload_errors`, `payload_heartbeat_room`, `payload_heartbeat_board`, and the error compare uses `ERR_NONE` (AC5). [firmware/gateway.yaml:112-117]
  - [ ] 1.3: Confirm there is **no** `homeassistant.event:` action and no API event fire in this handler (AC3).

- [ ] **Task 2: Ensure the log line carries the full decode on every heartbeat** (AC: 2,4)
  - [ ] 2.1: The current code logs room/board/uptime on the `ESP_LOGD` (normal) path but only includes the error byte on the `ESP_LOGW` (error) path. Add the error byte to the normal-path message (e.g. `... err=0x%02X`) so uptime+errors+room+board are all present on every heartbeat (AC2, AC4). Keep the two-level severity (`ESP_LOGW` when `errors != ERR_NONE`, `ESP_LOGD`/`ESP_LOGI` otherwise) — just make the normal path complete. [firmware/gateway.yaml:117-123]
  - [ ] 2.2: Confirm the message is decode-confirming (contains the decoded values), not static (AC4).

- [ ] **Task 3: Compile both handlers** (AC: 6)
  - [ ] 3.1: From `firmware/`, run `esphome compile gateway.yaml` with the Story 3.2 CAT_INPUT handler and this CAT_STATUS handler both present. Fix any errors.
  - [ ] 3.2: Confirm `firmware/README.md` "ESPHome Version" reflects the compiling version (`2026.5.0`).

## Dev Notes

### Approach & constraints (decision-aligned)

- **Keep the `if:`/`condition:` guard pattern** (consistent with Story 3.2 and the project's documented preference). Do not fold the guard into a single action lambda. [Source: memory esphome_on_frame_guard]
- **Heartbeat disposition (PoC):** log via ESPHome logger only; no HA event. [Source: architecture.md:179-181]
- **Protocol constants only**, including `ERR_NONE` for the error comparison. [Source: architecture.md:276-301]
- **CAN filtering:** CAT_STATUS base ID `0x600`, mask `0x600` matches the category bits (10:9) regardless of node. [Source: project-context.md "CAN bus filtering"; canbus_protocol.h:38-45]

### ⚠️ Byte-position note (now consistent everywhere)

The epic AC text has been corrected to match the header. Authoritative heartbeat layout (0-indexed): `[ver=0, type=1, uptime_h=2, errors=3, room=4, board=5, 0, 0]`. Use `payload_uptime/errors/heartbeat_room/heartbeat_board` — they encode the correct indices. The current handler already uses them correctly; preserve the mapping. [Source: canbus_protocol.h:95-99, 113-117]

### Current implementation (the thing you are verifying)

[firmware/gateway.yaml:104-123](../../firmware/gateway.yaml#L104-L123):

```yaml
- can_id: 0x600
  can_id_mask: 0x600
  then:
    - if:
        condition:
          lambda: 'if (x.size() < CAN_FRAME_SIZE) return false; return x[0] == PROTO_V1;'
        then:
          - lambda: |-
              const uint8_t room   = payload_heartbeat_room(x);
              const uint8_t board  = payload_heartbeat_board(x);
              const uint8_t uptime = payload_uptime(x);
              const uint8_t errors = payload_errors(x);
              if (errors != ERR_NONE) {
                ESP_LOGW("gw", "Node R%02uB%u error=0x%02X uptime=%uh",
                         room, board, errors, uptime);
              } else {
                ESP_LOGD("gw", "Heartbeat R%02uB%u uptime=%uh",
                         room, board, uptime);     // <-- add err=0x%02X here (Task 2.1)
              }
```

Only Task 2.1 (add the error byte to the `ESP_LOGD` line) is an actual change; the rest is verification.

### Source tree components to touch

- **UPDATE** [firmware/gateway.yaml](../../firmware/gateway.yaml) — CAT_STATUS `on_frame` entry only ([lines ~104-123](../../firmware/gateway.yaml#L104-L123)). Do not touch the CAT_INPUT handler (Story 3.2) or the `canbus:`/`api:` config.
- **READ-ONLY** [firmware/common/canbus_protocol.h](../../firmware/common/canbus_protocol.h) — provides `CAN_FRAME_SIZE`, `PROTO_V1`, `ERR_NONE`, `payload_uptime/errors/heartbeat_room/heartbeat_board`. Do not modify.
- **UPDATE** [firmware/README.md](../../firmware/README.md) — confirm "ESPHome Version" (Task 3.2) if not already set by Story 3.2.

### Testing standards

- **No unit-test framework.** Primary test is `esphome compile firmware/gateway.yaml` succeeding with both handlers (AC6). [Source: project-context.md]
- Heartbeat-in-log hardware verification (a powered node producing a heartbeat visible in the gateway log within ~60s) is exercised in **Story 4.1 (bench commissioning)**, not here. [Source: architecture.md:223-229]

### Previous story intelligence

- **Story 3.2** (CAT_INPUT) keeps the `if:`/`condition:` + YAML-action approach; mirror the guard convention here. Sequence: 3.2 done (or pattern agreed) before 3.3's compile gate, since AC6 needs both handlers present.
- **Epic 2 deferred (informational):** `uptime_h` silently overflows at 255 h (~10.6 days) — node-side `(uint8_t)((millis()/3600000UL)&0xFF)` wraps with no epoch flag. The gateway just logs the received byte. Do **not** try to "fix" it here. [Source: deferred-work.md:9]
- `ERR_NONE` is defined (`canbus_protocol.h:67`) — use it; do not compare against `0x00`. [Source: 3-1 review findings]
- ESP-IDF gateway lambdas have `to_string()`/`std::string()` available. [Source: project-context.md:37]

### Git intelligence

The CAT_STATUS handler in its current form is the product of `3d7830a` / `a5ee1f2`. Treat it as a near-complete starting point — verify and apply the small log-completeness fix.

### Project Structure Notes

- The two `on_frame` entries (CAT_INPUT 0x200, CAT_STATUS 0x600) are independent filter entries under the same `canbus:` component — editing one does not affect the other.
- No `nodes/` files are touched.

### References

- [Source: epics.md#Story-3.3 (lines 334-348, byte positions corrected)]
- [Source: architecture.md#Lambda-Safety-Pattern (lines 254-274)]
- [Source: architecture.md#Protocol-&-State-Management — heartbeat disposition (lines 179-181)]
- [Source: firmware/common/canbus_protocol.h — heartbeat decoders (lines 95-99, 113-117), ERR_NONE (line 67)]
- [Source: project-context.md — CAN bus filtering, C++ Lambda Rules, Testing & Validation]
- [Source: deferred-work.md — uptime_h overflow (line 9)]
- [Source: memory esphome_on_frame_guard — if:/condition: guard preference]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Change Log

## Status

ready-for-dev
