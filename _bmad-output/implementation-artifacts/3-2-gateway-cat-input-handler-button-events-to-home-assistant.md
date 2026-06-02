---
baseline_commit: cc3874dc2c3a7bb0c90f4e08dfc36e2932af7171
---

# Story 3.2: Gateway CAT_INPUT handler — button events to Home Assistant

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a developer,
I want the gateway's `on_frame` handler for CAT_INPUT frames to decode the payload and fire an `esphome.canbus_button` event to Home Assistant,
so that every button press on any node produces a correctly decoded event in HA Developer Tools.

## ⚠️ Critical Context — READ FIRST

The CAT_INPUT handler **already exists and is substantially complete** in [firmware/gateway.yaml](../../firmware/gateway.yaml#L83-L102). This story is mainly **verification + compile-gate + (deferred) hardware test**, with light hardening — **not** greenfield work.

**Approved approach (decided by Alberto, 2026-06-02):** The handler fires the HA event via the **ESPHome `homeassistant.event:` YAML action**, guarded by an `if:` / `condition:` block. This is intentional and matches the project's documented `on_frame` guard preference (clean action lambdas, no redundant re-checks).

**⚠️ Documented deviation from architecture:** [architecture.md:153-162, 416](../../_bmad-output/planning-artifacts/architecture.md#L153-L162) mandates a *single-lambda direct internal-API call* (`api::global_api_server->send_homeassistant_action`) and lists the `homeassistant.event:` YAML action as a gateway anti-pattern. **That mandate is overridden for this PoC.** Rationale: the YAML action is simpler, fully documented, and upgrade-stable; the internal API is undocumented and version-coupled. The dev MUST NOT refactor to the internal-API/single-lambda form. (Follow-up: architecture.md should be updated to record this reversal — see Decision Note.)

The decode logic and field mapping already present are **correct** (button=x[2], event=x[3], room=x[4], board=x[5]) — preserve them.

## Acceptance Criteria

1. **AC1 — Guard before any payload access:** For the CAT_INPUT entry (`can_id: 0x200`, `can_id_mask: 0x600`), the size guard `if (x.size() < CAN_FRAME_SIZE) return false;` is the **first check** in the `if:` `condition:` lambda, before any byte is indexed (NFR-2). Exact bound — not `x.empty()`, not the magic number `8`. [Source: epics.md:325; architecture.md:256-273; memory: esphome_on_frame_guard]

2. **AC2 — Version gate, silent discard:** The `condition:` also requires `x[0] == PROTO_V1`; when it is not met the frame is silently discarded — no log output, no HA event (the action branch simply does not run). [Source: epics.md:326]

3. **AC3 — Correct field decode via helpers:** For a valid frame, decoding uses the named helpers from `canbus_protocol.h`: `button = payload_button_index(x)` (x[2]), `event = event_type_str(payload_event_type(x))` (x[3]), `room = payload_room(x)` (x[4]), `board = payload_board(x)` (x[5]). No raw indices or magic numbers in the YAML lambdas. [Source: epics.md:327; architecture.md:276-301; project-context.md "single source of truth"]

4. **AC4 — Fire `esphome.canbus_button` via the YAML action:** The handler fires an `esphome.canbus_button` event to HA using the ESPHome `homeassistant.event:` action with `event: esphome.canbus_button` and the four data fields. [Source: epics.md:328 (mechanism overridden per Decision Note); architecture.md:195-206]

5. **AC5 — String field values, raw-integer format:** All event data field values are strings. `room`/`board`/`button` are raw decimal integers as strings (`"7"`, not `"room_7"`) via `to_string(...)`; `event` is the human-readable string from `event_type_str()` (`"click"`, `"double_click"`, `"triple_click"`, `"long_press"`, `"extra_long_press"`) via `std::string(...)`. [Source: epics.md:329; architecture.md:197-203; FR-6.3]

6. **AC6 — No staging globals:** No ESPHome globals are introduced to pass values between actions in this handler (FR-6.4). Each data-field `!lambda` decodes from `x` directly; no `globals:` entries are added for staging. [Source: epics.md:330; architecture.md:331-341]

7. **AC7 — Log before fire (observability):** The handler logs the decoded event to the ESPHome serial log (`ESP_LOGI`) **before** the `homeassistant.event:` action runs (NFR-8). The log line must contain the decoded values, confirming the decode ran. [Source: epics.md:331; architecture.md NFR-8]

8. **AC8 — Compile gate:** `esphome compile firmware/gateway.yaml` completes successfully from `firmware/` on ESPHome 2026.5.0. [Source: epics.md:311 carry-forward; architecture.md:210-212]

9. **AC9 — Hardware verification (deferred if no bench):** Pressing a button on node 100 or node 101 produces the correct `esphome.canbus_button` event in HA Developer Tools. If the physical bench is not yet assembled (Story 4.1), this AC is explicitly deferred and noted — the compile gate (AC8) and code review stand in until then. [Source: epics.md:332; architecture.md:223-229]

## Tasks / Subtasks

- [x] **Task 1: Verify the existing CAT_INPUT handler against ACs 1-7** (AC: 1,2,3,4,5,6,7)
  - [x] 1.1: Confirm the `if:` `condition:` lambda's **first** statement is the size guard `if (x.size() < CAN_FRAME_SIZE) return false;` and that it precedes the `x[0] == PROTO_V1` check (AC1, AC2). The current line is `if (x.size() < CAN_FRAME_SIZE) return false; return x[0] == PROTO_V1;` — verified unchanged/correct. [firmware/gateway.yaml:90]
  - [x] 1.2: Confirm all four data fields decode via the named helpers and that `event` uses `event_type_str(...)` (AC3). [firmware/gateway.yaml:99-102]
  - [x] 1.3: Confirm the `homeassistant.event:` action fires `esphome.canbus_button` (AC4) and all four values are strings via `to_string(...)`/`std::string(...)` (AC5). [firmware/gateway.yaml:96-102]
  - [x] 1.4: Confirm no `globals:` block exists for event staging and none is needed (AC6).
  - [x] 1.5: Confirm the `ESP_LOGI` decode line runs **before** the `homeassistant.event:` action and includes room/board/button/event (AC7). [firmware/gateway.yaml:92-95]
  - [x] 1.6: If any check fails, make the minimal edit to satisfy it. (No handler edits needed — AC1-AC7 already satisfied as written.)

- [x] **Task 2: Compile and record version** (AC: 8)
  - [x] 2.1: From `firmware/`, run `esphome compile gateway.yaml`. Resolved a pre-existing `api: password:` deprecation (removed in ESPHome 2026.1.0) by migrating to API encryption — see Completion Notes.
  - [x] 2.2: Confirm/record the ESPHome version in `firmware/README.md` under "ESPHome Version" (recorded `2026.5.0`, matching the Epic 2 node compiles).

- [x] **Task 3: Hardware verification or explicit deferral** (AC: 9)
  - [ ] 3.1: If the bench (Story 4.1) is assembled and HA is reachable: press each of the 5 event types on node 100 and node 101; confirm correctly decoded `esphome.canbus_button` events appear in HA Developer Tools. Capture evidence. — **Deferred: no bench yet (Story 4.1 in backlog).**
  - [x] 3.2: If no bench yet: marked AC9 deferred in Completion Notes, pointing to Story 4.2/4.3 (acceptance matrix) where it will be exercised.

### Review Findings

_Adversarial code review (bmad-code-review), 2026-06-02 — 3 layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor). AC1–AC7 independently confirmed against the committed handler; the only code delta vs baseline was the API-auth migration. 9 findings dismissed as noise/false-positive (e.g. "over-broad can_id_mask" = by-design category filter; "dangling ha_api_key" = grep-confirmed none)._

- [x] [Review][Patch] No message-type check in CAT_INPUT guard — APPLIED. Added `&& payload_type(x) == MSG_BUTTON_EVENT` to the `if:` `condition:` so a category-1 frame with a non-button message type (e.g. a future `MSG_CONFIG_ACK` node→gateway under CAT_INPUT) is no longer decoded/fired as a bogus `esphome.canbus_button`. [firmware/gateway.yaml:91]
- [x] [Review][Patch] Unknown event_type still fires to HA — APPLIED. Wrapped the `homeassistant.event:` action in a nested `if:` `condition:` guarding `event_type_str(payload_event_type(x)) != "unknown"`. Unknown types are still logged (observability) but no longer forwarded to HA, avoiding spurious automation triggers. Range check reuses `event_type_str()` (single source of truth) rather than duplicating the EVT_* bounds. [firmware/gateway.yaml:97-110]

_Patches re-verified: `esphome compile gateway.yaml` SUCCESS on ESPHome 2026.5.0 (13.76s) — AC8 still passes._
- [x] [Review][Defer] project-context.md mandates staging-globals, contradicting AC6 and shipped code — [project-context.md:64] and the "Key non-obvious fact" ([project-context.md:152]) both say "always stage values into globals first," but AC6 and the committed handler deliberately use per-field `!lambda` re-decode with no globals. Same class of doc/firmware contradiction the story already acknowledges for architecture.md; correct as a follow-up. [_bmad-output/project-context.md:64,152] — deferred, doc follow-up
- [x] [Review][Defer] No rate-limit/dedup on HA event firing — `homeassistant.event:` fires on every matching frame; a noisy bus or stuck/repeating frame floods the HA event bus. Low risk for human-paced clicks; pre-existing design, not introduced by this story. [firmware/gateway.yaml:97] — deferred, pre-existing design
- [x] [Review][Defer] README "pinned version" is doc-only + migration note omits HA re-adoption — the README records `2026.5.0` but there is no `esphome: min_version:` enforcement in YAML, and the encryption-migration note doesn't mention that an already-adopted device must be re-paired in HA with the new key (moot until a device is deployed). [firmware/README.md:67-74] — deferred, doc enhancement

## Dev Notes

### Approach & constraints (decision-aligned)

- **Keep the `homeassistant.event:` YAML action** fired from an `if:`/`condition:`-guarded branch. Do **not** refactor to `api::global_api_server` / single-lambda. This overrides architecture.md:153-162/416 for the PoC (see Decision Note). [Decision: Alberto, 2026-06-02]
- **Guard pattern (project preference):** the size/validity guard lives in the `if:` `condition:` lambda; action lambdas stay clean with no redundant re-checks. Size guard is the first statement and uses `CAN_FRAME_SIZE` (no magic `8`). [Source: memory esphome_on_frame_guard; architecture.md:256-273]
- **Protocol constants only.** All decoding uses named helpers/constants from `canbus_protocol.h`. No raw hex, bit shifts, or magic event-type numbers in YAML lambdas. [Source: architecture.md:276-301; project-context.md]
- **HA event field format** (all strings): `room`/`board`/`button` = raw integer as string (`"7"`, not `"room_7"`); `event` = human-readable from `event_type_str()`. ESP-IDF gateway lambdas have `to_string()`/`std::string()` available. [Source: architecture.md:197-203; project-context.md:37]
- **No globals for staging.** Each data-field `!lambda` re-decodes from `x`; this is acceptable here (the helpers are cheap pure functions). Do not add globals to "optimize" this. [Source: architecture.md:331-341; FR-6.4]

### Current implementation (the thing you are verifying)

[firmware/gateway.yaml:83-102](../../firmware/gateway.yaml#L83-L102):

```yaml
on_frame:
  - can_id: 0x200
    can_id_mask: 0x600
    then:
      - if:
          condition:
            lambda: 'if (x.size() < CAN_FRAME_SIZE) return false; return x[0] == PROTO_V1;'
          then:
            - lambda: |-
                ESP_LOGI("gw", "Button R%02uB%u btn%u %s",
                         payload_room(x), payload_board(x), payload_button_index(x),
                         event_type_str(payload_event_type(x)).c_str());
            - homeassistant.event:
                event: esphome.canbus_button
                data:
                  room: !lambda 'return to_string(payload_room(x));'
                  board: !lambda 'return to_string(payload_board(x));'
                  button: !lambda 'return to_string(payload_button_index(x));'
                  event: !lambda 'return std::string(event_type_str(payload_event_type(x)));'
```

This already satisfies AC1-AC7. The story's real value is the **compile gate** (AC8) and **hardware confirmation / explicit deferral** (AC9), plus locking in the approved approach so a later reviewer doesn't "fix" it toward the internal-API form.

### Source tree components to touch

- **UPDATE (verify, likely no change)** [firmware/gateway.yaml](../../firmware/gateway.yaml) — CAT_INPUT `on_frame` entry only (lines ~83-102). Leave the CAT_STATUS entry for Story 3.3 and the `canbus:`/`api:` config intact.
- **READ-ONLY** [firmware/common/canbus_protocol.h](../../firmware/common/canbus_protocol.h) — provides `CAN_FRAME_SIZE`, `PROTO_V1`, `payload_button_index/event_type/room/board`, `event_type_str`. Do **not** modify; shared single source of truth — any change forces reflashing all nodes.
- **UPDATE** [firmware/README.md](../../firmware/README.md) — "ESPHome Version" line (Task 2.2) if not already recorded.

### Testing standards

- **No unit-test framework.** Primary test is `esphome compile firmware/gateway.yaml` succeeding (AC8). [Source: project-context.md "Testing & Validation"]
- Hardware/HA verification (AC9) is a manual Developer-Tools check, deferred to the Epic 4 acceptance matrix if no bench is available now.
- The `on_frame → homeassistant.event` chain has not been compiled/tested against hardware before this story — treat as unverified until AC8 passes. [Source: project-context.md line 79]

### Previous story intelligence (Story 3.1)

- Gateway is Waveshare **ESP32-S3-RS485-CAN**, native TWAI on **TX=GPIO15, RX=GPIO16**, **125 kbps**, `esp-idf` framework (never Arduino). [Source: 3-1 Dev Notes; project-context.md]
- 3-1's review briefly **restored globals** for HA staging as a patch, but the committed gateway.yaml has **no globals** — it uses per-field `!lambda` decode under the `homeassistant.event:` action. That is the approved state. Do not reintroduce globals. [Source: 3-1 review findings]
- `ERR_NONE` and all button/heartbeat helpers already exist in `canbus_protocol.h` — no header changes needed.
- Epic 2 node compiles ran on **ESPHome 2026.5.0** (SUCCESS). [Source: deferred-work.md:22]

### Git intelligence

Recent commits: `a5ee1f2 fix: gateway compiles under esp-idf`, `3d7830a fix: address deferred items from Epic 2 reviews`. The current gateway.yaml is their product — handlers exist and use the approved YAML-action approach.

### Decision Note (architecture deviation — recorded)

Architecture.md mandates single-lambda direct internal-API firing and forbids `homeassistant.event:` on the gateway (architecture.md:153-162, 416, 579). **Alberto decided on 2026-06-02 to keep the `homeassistant.event:` YAML action** for the PoC: it is simpler, documented, and upgrade-stable, whereas the internal API is undocumented and version-coupled. This story implements that decision. **Recommended follow-up (not in this story's scope):** update architecture.md to record the reversal so the planning artifact and the firmware no longer contradict — run `correct-course` or ask Claude to amend the architecture doc.

### Project Structure Notes

- Editing only the CAT_INPUT `on_frame` entry keeps Story 3.3 (CAT_STATUS) cleanly separable — the two are independent `on_frame` filter entries under the same `canbus:` component.
- No `nodes/` files are touched (gateway is hand-authored, not generated).

### References

- [Source: epics.md#Story-3.2 (lines 314-332)]
- [Source: architecture.md#HA-Integration-Interface (lines 195-206)]
- [Source: architecture.md#Lambda-Safety-Pattern (lines 254-274)]
- [Source: architecture.md#Protocol-&-State-Management & anti-patterns (lines 151-162, 416, 579) — DEVIATED per Decision Note]
- [Source: project-context.md — C++ Lambda Rules, CAN bus filtering, Testing & Validation]
- [Source: firmware/common/canbus_protocol.h — decoders & constants]
- [Source: memory esphome_on_frame_guard — if:/condition: guard preference]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (Claude Code, bmad-dev-story workflow)

### Debug Log References

- `esphome compile gateway.yaml` — **first attempt FAILED** at config validation: `api: password:` option removed in ESPHome 2026.1.0.
- `esphome compile gateway.yaml` — **second attempt SUCCESS** (66.84s) after migrating to API encryption. ESP32-S3 image created; RAM 14.1%, Flash 9.5%.

### Completion Notes List

- **AC1-AC7 verified, no handler edits needed.** The CAT_INPUT `on_frame` entry ([firmware/gateway.yaml:85-102](../../firmware/gateway.yaml#L85-L102)) already satisfies all seven behavioral ACs:
  - AC1/AC2: size guard `if (x.size() < CAN_FRAME_SIZE) return false;` is the first statement and precedes `x[0] == PROTO_V1` in the `if:`/`condition:` lambda; failed version check silently discards (no log, no event).
  - AC3: all fields decode via named helpers from `canbus_protocol.h` (`payload_room/board/button_index`, `event_type_str(payload_event_type(x))`); no raw indices or magic numbers.
  - AC4: fires `esphome.canbus_button` via the approved `homeassistant.event:` YAML action (architecture.md deviation honored — NOT refactored to internal-API/single-lambda).
  - AC5: `room`/`board`/`button` are raw-integer strings via `to_string(...)`; `event` is the human-readable string via `std::string(event_type_str(...))`.
  - AC6: no `globals:` block exists; each `!lambda` re-decodes from `x` directly.
  - AC7: `ESP_LOGI` decode line runs before the `homeassistant.event:` action and logs room/board/button/event.
- **AC8 compile gate PASSED on ESPHome 2026.5.0** — but required resolving a pre-existing blocker unrelated to the handler: gateway.yaml (from Story 3.1) used `api: password:`, **removed in ESPHome 2026.1.0**. gateway.yaml had never been compiled before (project-context.md:79), so this surfaced at the first compile gate. Per Alberto's decision (2026-06-02), migrated to API encryption: `api: encryption: key: !secret api_encryption_key`. Generated a key with `openssl rand -base64 32`, added `api_encryption_key` to `secrets.yaml.example` (placeholder) and to local `secrets.yaml` (gitignored, real key). This preserves Story 3.1's authenticated-API intent via the ESPHome-recommended mechanism. **Carry-forward note:** this is effectively a Story 3.1 fix — the Epic 3 retro / a future doc pass may want to record it against 3.1.
- **AC9 hardware verification: DEFERRED.** No physical bench yet — Story 4.1 (`4-1-bench-assembly-and-hardware-commissioning`) is in backlog. Per Task 3.2, AC9 (pressing the 5 event types on nodes 100/101 and confirming decoded `esphome.canbus_button` events in HA Developer Tools) is deferred to the Epic 4 acceptance matrix (Stories 4.2/4.3). The compile gate (AC8) and code review stand in until then.
- **Architecture deviation preserved (intentional):** the `homeassistant.event:` YAML action was kept per the Decision Note (Alberto, 2026-06-02). Did NOT refactor to `api::global_api_server->send_homeassistant_action`. Follow-up to update architecture.md remains out of scope for this story.

### File List

- `firmware/gateway.yaml` — MODIFIED: migrated `api: password:` → `api: encryption: key: !secret api_encryption_key` (compile-gate blocker; CAT_INPUT handler unchanged).
- `firmware/secrets.yaml.example` — MODIFIED: replaced `ha_api_key` placeholder with `api_encryption_key` + key-generation note.
- `firmware/README.md` — MODIFIED: recorded pinned ESPHome version `2026.5.0` and an API-encryption migration note under "ESPHome Version".
- `firmware/secrets.yaml` — CREATED (local only, gitignored): real `api_encryption_key` for local compile; not committed.

## Change Log

- 2026-06-02: Verified CAT_INPUT `on_frame` handler against AC1-AC7 (no handler changes required). Passed AC8 compile gate on ESPHome 2026.5.0 after migrating the gateway API from removed `password:` auth to `encryption:` key. Recorded ESPHome version in README. AC9 (hardware) explicitly deferred to Epic 4 acceptance matrix (no bench yet). Status → review.
- 2026-06-02: Code review (bmad-code-review, 3 layers). AC1-AC7 independently re-confirmed against committed handler. Applied 2 hardening patches: (1) message-type guard `payload_type(x) == MSG_BUTTON_EVENT`; (2) skip HA fire for unknown event types (still logged). Recompiled SUCCESS on ESPHome 2026.5.0. 3 items deferred (doc/design follow-ups), 9 dismissed as noise. Status → done.

## Status

done
