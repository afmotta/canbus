---
stepsCompleted: [1, 2, 3, 4, 5, 6]
documentsInventoried:
  prd: "_bmad-output/planning-artifacts/prds/prd-canbus-2026-05-29/prd.md"
  architecture: "_bmad-output/planning-artifacts/architecture.md"
  epics: "_bmad-output/planning-artifacts/epics.md"
  ux: null
---

# Implementation Readiness Assessment Report

**Date:** 2026-05-31
**Project:** canbus

---

## PRD Analysis

### Functional Requirements

| ID     | Requirement                                                                                                                                                                                   |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR-1.1 | Each node firmware SHALL detect 5 event types per button (single click, double click, triple click, long press 1–3 s, extra-long press 3+ s) using ESPHome `on_multi_click`.                  |
| FR-1.2 | Multi-click patterns SHALL be ordered longest-first (triple → double → single → long → extra-long) to prevent shadowing.                                                                      |
| FR-1.3 | Click timing thresholds are compile-time constants; runtime adjustment is out of scope.                                                                                                       |
| FR-1.4 | Each node SHALL support up to 8 buttons per board. Nodes standardize on the 8-button set (`btn0`–`btn7`) in `common/base_node.yaml`.                                                          |
| FR-2.1 | On each button event, the node SHALL transmit a CAN frame with CAN ID = `(CAT_INPUT << 9) \| node_id` and the 8-byte button event payload.                                                    |
| FR-2.2 | The node SHALL validate `x.size() >= 8` in all CAN frame receive lambdas before indexing any byte.                                                                                            |
| FR-2.3 | CAN bus speed SHALL be 125 kbps.                                                                                                                                                              |
| FR-2.4 | The node SHALL use the MCP2515 CAN controller via SPI0 with a 16 MHz clock [ASSUMPTION: confirm oscillator].                                                                                  |
| FR-3.1 | Each node SHALL transmit a heartbeat frame every 30 seconds with CAN ID = `(CAT_STATUS << 9) \| node_id` and 8-byte heartbeat payload.                                                        |
| FR-3.2 | Heartbeat error flags (payload byte 4) SHALL be set: bit 0 (0x01) for CAN TX error/timeout, bit 1 (0x02) for bus-off; 0x00 when healthy.                                                      |
| FR-4.1 | All CAN frame construction and decoding SHALL use `canbus_protocol.h`; raw bit shifts and magic numbers SHALL NOT appear in YAML lambdas.                                                     |
| FR-4.2 | `canbus_protocol.h` SHALL be included by both node and gateway firmware.                                                                                                                      |
| FR-5.1 | Gateway SHALL receive all CAT_INPUT frames using mask-based filtering: `can_id: 0x200`, `can_id_mask: 0x600`.                                                                                 |
| FR-5.2 | Gateway SHALL receive all CAT_STATUS frames using mask-based filtering: `can_id: 0x600`, `can_id_mask: 0x600`.                                                                                |
| FR-5.3 | Gateway CAN interface SHALL use native TWAI on GPIO15 (TX) and GPIO16 (RX) at 125 kbps.                                                                                                       |
| FR-6.1 | On receiving a valid CAT_INPUT frame, gateway SHALL fire `esphome.canbus_button` event with string fields: `room`, `board`, `button`, `event`.                                                |
| FR-6.2 | On receiving a valid CAT_STATUS frame, gateway SHALL fire `esphome.canbus_heartbeat` event with string fields: `room`, `board`, `uptime`, `errors`.                                           |
| FR-6.3 | All event data field values SHALL be strings; integer values SHALL be converted via `to_string()` or `std::string()`.                                                                         |
| FR-6.4 | Values needed in `homeassistant.event` data blocks SHALL be staged into ESPHome globals first.                                                                                                |
| FR-7.1 | Gateway SHALL connect to Home Assistant via ESPHome native API over WiFi [ASSUMPTION: credentials provided at build time].                                                                    |
| FR-7.2 | [ASSUMPTION] Home Assistant instance is on the same WiFi network and reachable from the gateway.                                                                                              |
| FR-8.1 | Node YAML files SHALL be generated by `generate_nodes.py` from `nodes.csv`; hand-editing files in `nodes/` is prohibited.                                                                     |
| FR-8.2 | `nodes.csv` SHALL define: `node_id`, `floor`, `room`, `board`, `location`, `gpio_list` for each node.                                                                                         |
| FR-8.3 | For the PoC, `nodes.csv` SHALL contain exactly 2 node entries with distinct `node_id` values, distinct `room` values, and assigned button GPIO lists.                                         |
| FR-8.4 | `generate_nodes.py` SHALL print a CAN ID map on completion; the map SHALL be reviewed for duplicate IDs before flashing.                                                                      |
| FR-9.1 | For each of the 5 event types, pressing the corresponding sequence on node 0 SHALL produce an `esphome.canbus_button` event in HA with correct `room`, `board`, `button`, and `event` values. |
| FR-9.2 | Same validation SHALL pass for node 1 (different `room` value).                                                                                                                               |
| FR-9.3 | Within 60 seconds of power-on, each node SHALL emit at least one heartbeat visible as `esphome.canbus_heartbeat` in HA.                                                                       |
| FR-9.4 | Events from node 0 and node 1 SHALL be distinguishable by `room` and `board` field values.                                                                                                    |
| FR-9.5 | All 10 event-type combinations (5 types × 2 nodes) SHALL produce a correctly decoded HA event with no missing or blank fields. PoC passes only when all 10 are verified.                      |
| FR-9.6 | ESPHome logs on the gateway SHALL show zero CAN error frames during the validation run; any error frame is a blocking defect.                                                                 |

**Total FRs: 26**

---

### Non-Functional Requirements

| ID    | Requirement                                                                                                                                               |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| NFR-1 | Both node and gateway firmware SHALL compile successfully with `esphome compile` before any hardware is connected. A failed compile is a blocking defect. |
| NFR-2 | Every CAN frame receive lambda SHALL guard against short frames with `x.size() >= N` before indexing. Absence of this guard is a blocking defect.         |
| NFR-3 | `canbus_protocol.h` is the sole location for protocol constants. Any constant duplicated in YAML is a defect.                                             |
| NFR-4 | Gateway SHALL use `esp-idf` framework. Arduino framework is incompatible with `esp32_can` on ESP32-S3 and SHALL NOT be used on the gateway.               |
| NFR-5 | Nodes SHALL have no WiFi, no ESPHome API, no OTA, no web server, no network logger.                                                                       |
| NFR-6 | All devices on the bus SHALL use 125 kbps. Mismatched speeds are not recoverable without power cycling.                                                   |
| NFR-7 | The bus SHALL have exactly two 120 Ω termination resistors, one at each physical end.                                                                     |

**Total NFRs: 7**

---

### Additional Requirements / Constraints

- **Open Questions (hardware-blocking):** OQ-1 (button GPIO numbers), OQ-2 (INT pin = GPIO20?), OQ-3 (16 MHz oscillator?) must be resolved before firmware can be compiled. These are explicitly called out as blocking in the PRD.
- **Deployment pre-requisite:** CANBed RP2040 boards require soldering before first use.
- **Protocol frozen:** `canbus_protocol.h` is treated as frozen; any change requires reflashing all nodes (no OTA).
- **PoC scope:** CAT_OUTPUT (gateway→node commands), HA dashboard, multi-gateway topology, and production automations are explicitly out of scope.

---

## Epic Coverage Validation

### Coverage Matrix

| FR     | PRD Requirement (summary)                         | Epic / Story                                         | Status                                                                                            |
| ------ | ------------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| FR-1.1 | 5 event types via `on_multi_click`                | Epic 2 / Story 2.2                                   | ✓ Covered                                                                                         |
| FR-1.2 | Patterns ordered longest-first                    | Epic 2 / Story 2.2                                   | ✓ Covered                                                                                         |
| FR-1.3 | Timing thresholds are compile-time constants      | Epic 2 / Story 2.2                                   | ✓ Covered                                                                                         |
| FR-1.4 | Up to 6 buttons per board                         | Epic 2 / Story 2.1–2.2                               | ✓ Covered                                                                                         |
| FR-2.1 | Node transmits CAN frame on button event          | Epic 2 / Story 2.2                                   | ✓ Covered                                                                                         |
| FR-2.2 | `x.size() >= 8` guard in receive lambdas          | Epic 2 / Story 2.3                                   | ✓ Covered (uses `CAN_FRAME_SIZE` constant)                                                        |
| FR-2.3 | 125 kbps CAN bus speed                            | Epic 2 / Story 2.1; Epic 3 / Story 3.1               | ✓ Covered                                                                                         |
| FR-2.4 | MCP2515 via SPI0, 16 MHz clock                    | Epic 2 / Story 2.1                                   | ✓ Covered                                                                                         |
| FR-3.1 | Heartbeat frame every 30 s                        | Epic 2 / Story 2.3                                   | ✓ Covered                                                                                         |
| FR-3.2 | Error flags in heartbeat byte 4                   | Epic 2 / Story 2.3                                   | ✓ Covered                                                                                         |
| FR-4.1 | All frame logic via `canbus_protocol.h`           | Epic 1 / Story 1.3 (expanded to FR-4.1–4.4 in epics) | ✓ Covered                                                                                         |
| FR-4.2 | Header included by node and gateway               | Epic 1 / Story 1.3                                   | ✓ Covered                                                                                         |
| FR-5.1 | CAT_INPUT mask filtering (0x200 / 0x600)          | Epic 3 / Story 3.2                                   | ✓ Covered                                                                                         |
| FR-5.2 | CAT_STATUS mask filtering (0x600 / 0x600)         | Epic 3 / Story 3.3                                   | ✓ Covered                                                                                         |
| FR-5.3 | TWAI on GPIO15/16 at 125 kbps                     | Epic 3 / Story 3.1                                   | ✓ Covered                                                                                         |
| FR-6.1 | Fire `esphome.canbus_button` with 4 string fields | Epic 3 / Story 3.2                                   | ✓ Covered                                                                                         |
| FR-6.2 | Fire `esphome.canbus_heartbeat` HA event          | Epic 3 / Story 3.3                                   | ⚠️ **CONFLICT** — Epics changed this to gateway log only; no HA event in PoC                       |
| FR-6.3 | All event data values SHALL be strings            | Epic 3 / Story 3.2                                   | ✓ Covered                                                                                         |
| FR-6.4 | Stage values into ESPHome globals before HA event | Epic 3 / Story 3.2                                   | ⚠️ **CONFLICT** — Epics explicitly reversed this: direct `api::global_api_server` call, no globals |
| FR-7.1 | ESPHome native API over WiFi                      | Epic 3 / Story 3.1                                   | ✓ Covered                                                                                         |
| FR-7.2 | HA on same network (assumption)                   | Epic 3 / Story 3.1 (secrets management)              | ✓ Covered                                                                                         |
| FR-8.1 | Node YAML generated by `generate_nodes.py`        | Epic 1 / Story 1.4                                   | ✓ Covered                                                                                         |
| FR-8.2 | `nodes.csv` fields defined                        | Epic 1 / Story 1.4                                   | ✓ Covered                                                                                         |
| FR-8.3 | Exactly 2 node entries in PoC                     | Epic 1 / Story 1.4                                   | ✓ Covered (epics specifies IDs 100 and 101)                                                       |
| FR-8.4 | CAN ID map printed and reviewed                   | Epic 1 / Story 1.4                                   | ✓ Covered                                                                                         |
| FR-9.1 | 5 event types validated on node 0 in HA           | Epic 4 / Story 4.2                                   | ✓ Covered (node ID updated to 100)                                                                |
| FR-9.2 | Same validation for node 1                        | Epic 4 / Story 4.3                                   | ✓ Covered (node ID updated to 101)                                                                |
| FR-9.3 | Heartbeat visible within 60 s of power-on         | Epic 4 / Story 4.1                                   | ✓ Covered (target: gateway log, consistent with FR-6.2 change)                                    |
| FR-9.4 | Nodes distinguishable by room and board           | Epic 4 / Story 4.3                                   | ✓ Covered                                                                                         |
| FR-9.5 | All 10 combinations produce correct HA events     | Epic 4 / Story 4.3                                   | ✓ Covered                                                                                         |
| FR-9.6 | Zero CAN error frames in gateway logs             | Epic 4 / Stories 4.2–4.3                             | ✓ Covered                                                                                         |

### Missing Requirements

No PRD FRs are missing coverage. All 26 FRs are traced to at least one epic and story.

However, two PRD requirements were **deliberately revised** during epic creation — these are design evolution decisions, not gaps. They must be confirmed by the product owner:

#### FR-6.2 — Heartbeat destination (PRD vs Epics conflict)

- **PRD FR-6.2:** Gateway SHALL fire `esphome.canbus_heartbeat` HA event with `room`, `board`, `uptime`, `errors` fields.
- **Epics FR-6.2:** Gateway SHALL log heartbeat frames via ESPHome logger only — no HA event fired in PoC.
- **Impact:** The PoC acceptance criteria (FR-9.3) were updated to match the epics version (gateway log), not HA Developer Tools. These two documents are internally consistent with each other, but inconsistent with the PRD.
- **Recommendation:** Confirm which is correct. The epics rationale (simpler PoC; HA heartbeat event is deferred) is sound for a PoC, but the PRD is the authoritative source of truth.

#### FR-6.4 — ESPHome globals for event staging (PRD vs Epics conflict)

- **PRD FR-6.4:** Values SHALL be staged into ESPHome globals before `homeassistant.event` blocks.
- **Epics FR-6.4:** Gateway SHALL fire HA events via `api::global_api_server` directly in a single lambda — no globals.
- **Impact:** These two approaches are mutually exclusive implementation strategies. The epics approach avoids globals entirely by using the lower-level C++ API. The PRD approach uses ESPHome's declarative globals staging.
- **Recommendation:** The epics approach is noted as requiring verification against the pinned ESPHome source (Story 3.2 AC). Confirm this is the agreed implementation strategy.

### Additional Observations (Epics additions not in PRD)

The epics added value beyond the PRD — these are improvements, not gaps:

- **FR-4 expanded:** PRD has FR-4.1–4.2; epics adds FR-4.3 and FR-4.4 (no magic numbers in YAML lambdas; dual-toolchain compile validation). These are safe additions.
- **NFR-8 (Gateway observability):** New — gateway lambda SHALL produce log output for each event decoded/fired. Good addition.
- **NFR-9 (Repeatable logged validation):** New — HA event log SHALL be captured as artifacts (screenshots/exports). Essential for sign-off rigour.
- **Node IDs 100/101:** PRD says "node 0 and node 1"; epics specifies 100 and 101 (ground floor range 100–199). Consistent with a defined node ID allocation scheme.
- **Story 1.1 (Directory restructure):** Adds a concrete pre-compile gate — move firmware from `docs/esphome_canbus/` to `firmware/`. Not in PRD but necessary given current repo state.
- **Story 1.2 (Hardware OQ resolution):** Formalises the PRD open questions (OQ-1, OQ-2, OQ-3) as a blocked story with explicit ACs. Good.

### Coverage Statistics

- Total PRD FRs: 26
- FRs fully covered in epics: 24
- FRs with deliberate revision (conflicts requiring confirmation): 2 (FR-6.2, FR-6.4)
- FRs missing entirely: 0
- Coverage: **100%** (with 2 conflicts to confirm)

---

## UX Alignment Assessment

### UX Document Status

Not found — and not required.

### Alignment Issues

None. This is an embedded IoT firmware project with no user interface. Physical buttons are hardware inputs; HA Developer Tools is used for validation only and requires no UX design.

### Warnings

None. The epics document explicitly states UX is N/A for this project.

---

## Epic Quality Review

### Epic Structure Validation

#### Epic 1: Firmware Project Foundation

**User Value:** Borderline — this is infrastructure/setup, not user-facing. However, for a firmware PoC with a brownfield starting point (files in `docs/esphome_canbus/`), a foundation epic is unavoidable and appropriate. The "user" is the developer; the value is a compilable, correctly organized project. **Accepted for this project type.**

**Independence:** ✓ Stands alone. No dependency on any other epic.

**Story sequencing within Epic 1:**
- Story 1.1 (directory restructure) → Story 1.2 (hardware OQ research, writes to `firmware/README.md` created in 1.1) → Story 1.3 (protocol header) → Story 1.4 (code gen, depends on 1.2 GPIO values + 1.3 header path)
- All dependencies are backward-looking ✓

#### Epic 2: Node Firmware — Button Events & Heartbeat Over CAN

**User Value:** ✓ User-centric — "Alberto can press any button type and observe correct CAN frames." Clear outcome.

**Independence:** ✓ Requires only Epic 1 output. Does not require Epic 3.

**Story sequencing within Epic 2:**
- Story 2.1 (SPI + MCP2515 base config) → Story 2.2 (button package, 5 event types) → Story 2.3 (heartbeat + lambda safety guard + flash)
- All dependencies are backward-looking ✓
- Note: Stories 2.1 and 2.2 compile only; Story 2.3 is the first flash. This sequencing is correct — flash only after all node firmware is in place.

#### Epic 3: Gateway Firmware — Home Assistant Integration

**User Value:** ✓ Very user-centric — "Alberto presses a button and sees the decoded event in HA Developer Tools."

**Independence:** ✓ Requires Epics 1 and 2 outputs. Does not require Epic 4.

**Story sequencing within Epic 3:**
- Story 3.1 (gateway base config, compile gate) → Story 3.2 (CAT_INPUT handler) → Story 3.3 (CAT_STATUS handler)
- All dependencies are backward-looking ✓

#### Epic 4: PoC Validation & Sign-off

**User Value:** ✓ Crystal clear — 10-combination acceptance matrix, artifacts, official sign-off.

**Independence:** ✓ Requires Epics 1–3. No circular dependencies.

**Story sequencing within Epic 4:**
- Story 4.1 (bench assembly, hardware commissioning) → Story 4.2 (node 100 acceptance matrix) → Story 4.3 (node 101 + sign-off)
- All dependencies are backward-looking ✓

---

### Best Practices Compliance Checklist

| Check                           | E1                            | E2  | E3  | E4  |
| ------------------------------- | ----------------------------- | --- | --- | --- |
| Delivers user value             | ⚠️ Infrastructure (acceptable) | ✓   | ✓   | ✓   |
| Epic independence               | ✓                             | ✓   | ✓   | ✓   |
| Stories appropriately sized     | ✓                             | ✓   | ✓   | ✓   |
| No forward dependencies         | ✓                             | ✓   | ✓   | ✓   |
| Clear ACs in Given/When/Then    | ✓                             | ✓   | ✓   | ✓   |
| Compile/validation gate present | ✓                             | ✓   | ✓   | ✓   |
| FR traceability maintained      | ✓                             | ✓   | ✓   | ✓   |

---

### Quality Findings

#### 🟠 Major Issues

**Issue QA-1 — Story 3.2: Hidden technical risk embedded as an AC precondition**

Story 3.2 includes: *"the exact ESPHome C++ API method for direct HA event firing has been verified against the pinned ESPHome source before implementation."*

This is a research/discovery prerequisite baked into an AC rather than surfaced as a dedicated spike or story. The `api::global_api_server` method's signature, accessibility, and behaviour are unverified. If the approach doesn't work (wrong method name, not exposed in the ESPHome public API, or changed between versions), the entire gateway event strategy must be revised mid-story — at which point the approach from PRD FR-6.4 (globals staging) may need to be reinstated.

**Risk:** This is also the root cause of the FR-6.4 conflict (PRD vs Epics). The epics chose the `api::global_api_server` approach, but deferred verification. If verification fails, there is no fallback documented.

**Recommendation:** Extract "verify `api::global_api_server` method signatures against pinned ESPHome source" as an explicit AC in Story 1.3 (which already pins ESPHome) or as a dedicated discovery step at the start of Story 3.1. Define the fallback (globals staging per PRD FR-6.4) if the direct approach fails.

**Issue QA-2 — FR-6.2 / FR-6.4 conflicts not resolved in epics**

As identified in the coverage analysis, the epics modified two PRD requirements (FR-6.2 heartbeat → log only; FR-6.4 globals → direct API). These are valid design decisions but they are not documented as explicit PRD amendments or change decisions in the epics document. The `.decision-log.md` in the PRD folder may contain this rationale, but it is not cross-referenced from the epics.

**Recommendation:** Add a "Design Decisions" or "PRD Delta" section to `epics.md` documenting these two intentional deviations from the PRD, with the reasoning. This keeps the PRD as the authoritative record and the epics as the refined implementation contract.

#### 🟡 Minor Concerns

**QA-3 — Story 1.1 scope breadth:** Story 1.1 combines directory restructure, `.gitignore` update, `secrets.yaml.example` creation, `README.md` creation, and a config-check compile into one story. For a small PoC this is fine, but the compile gate at the end ("exits without path resolution errors") depends on `canbus_protocol.h` existing — which is Story 1.3. The compile check for `gateway.yaml` specifically will fail if the header isn't present. Consider whether the Story 1.1 compile gate should be limited to `esphome config` (YAML parse only) rather than a full path-resolution check.

**QA-4 — ESPHome version pinning timing:** "Record the ESPHome version" appears in Story 3.1 ACs. However, the first compile happens in Epic 1 (Stories 1.3 and 1.4 compile node YAML). If a different ESPHome version is used for Epic 1 vs Epic 3, there is a toolchain divergence risk. Consider adding "record ESPHome version" to Story 1.3 (first compile) and enforcing that all subsequent compiles use the same version.

**QA-5 — Validation artifact storage unspecified until Story 4.2:** The `validation/` directory for artifact storage is introduced only in Story 4.2. No earlier story establishes or documents this directory. Minor, but Story 4.1 bench commissioning photos/log captures could also benefit from this directory existing earlier.

#### ✅ Notable Strengths

- All 4 epics have concrete, measurable "done" conditions — no ambiguity about when an epic is complete.
- Compile gates are distributed across epics (Stories 1.3, 2.1, 2.2, 2.3, 3.1) rather than consolidated at the end — firmware compilation issues are caught early.
- Story 1.2 (hardware OQ resolution) correctly gates all firmware authoring — the ACs require documentation with source references, preventing "I think it's GPIO20" assumptions.
- Story 4.3 includes `firmware/VALIDATION.md` sign-off record with ESPHome version, hardware values, and artifact locations — excellent for repeatability.
- NFR-9 (artifact capture requirement) is a strong addition vs PRD — eyeball-only validation is explicitly rejected.

---

## Summary and Recommendations

### Overall Readiness Status

**READY WITH CONDITIONS**

The planning artefacts are solid and implementation can begin on Epic 1 immediately. Two issues must be resolved before starting Story 3.2 (gateway CAT_INPUT handler). No critical violations were found.

### Issues Summary

| #    | Severity | Issue                                                                             | Blocks               |
| ---- | -------- | --------------------------------------------------------------------------------- | -------------------- |
| QA-1 | 🟠 Major  | `api::global_api_server` approach unverified — no fallback documented if it fails | Story 3.2            |
| QA-2 | 🟠 Major  | FR-6.2 and FR-6.4 PRD deviations not documented in epics                          | Story 3.2, Story 3.3 |
| QA-3 | 🟡 Minor  | Story 1.1 compile gate may fail without `canbus_protocol.h` (Story 1.3)           | Story 1.1            |
| QA-4 | 🟡 Minor  | ESPHome version pinning deferred to Story 3.1; first compile is in Story 1.3      | Story 1.3            |
| QA-5 | 🟡 Minor  | `validation/` artifact directory not established until Story 4.2                  | Story 4.1            |

### Recommended Next Steps

1. **Begin Epic 1 now.** Stories 1.1–1.4 are unblocked and well-specified. Start with Story 1.1 (directory restructure) then Story 1.2 (hardware OQ resolution from board docs).

2. **Resolve QA-4 during Story 1.3.** When you run the first compile for `canbus_protocol.h`, record the exact ESPHome version in `firmware/README.md` immediately. Use that pinned version for all subsequent compiles.

3. **Fix QA-3 before closing Story 1.1.** Limit the Story 1.1 compile gate to `esphome config` (YAML parse/path check only), not a full compile — since `canbus_protocol.h` won't exist yet. Full compile gate belongs in Story 1.3.

4. **Before starting Story 3.1, document the PRD delta (QA-2).** Add a "Design Decisions vs PRD" note to `epics.md` or the decision log for FR-6.2 (heartbeat → log only) and FR-6.4 (globals → direct API). This keeps the record clean.

5. **Treat QA-1 as the highest-risk item in Epic 3.** At the start of Story 3.1 (first gateway compile), verify `api::global_api_server` method signatures in the pinned ESPHome source. If the approach doesn't work, the fallback is PRD FR-6.4 (globals staging). Document this contingency explicitly so Story 3.2 is not blocked by a discovery mid-implementation.

### Final Note

This assessment identified **5 issues** across **2 categories** (major: 2, minor: 3). No critical violations. The planning is well-structured for a firmware PoC of this scope — the epics are internally consistent, all 26 PRD FRs are traced, acceptance criteria are specific and testable, and the compile-first discipline is enforced throughout.

The two major issues both converge on the same risk: the gateway's direct `api::global_api_server` event-firing approach. Address this proactively during Epic 1/early Epic 3 and the remainder of implementation should proceed smoothly.

**Assessment completed:** 2026-05-31
**Assessed by:** Claude (Implementation Readiness skill)
