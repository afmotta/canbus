# Sprint Change Proposal — 2026-06-02

**Trigger:** Gateway HA event firing mechanism decision reversal
**Scope:** Minor (documentation reconciliation only)
**Status:** Approved & applied
**Author:** Alberto (decision) / Claude (correct-course)

## 1. Issue Summary

During create-story for Epic 3, analysis found the gateway firmware
(`firmware/gateway.yaml`) already fires `esphome.canbus_button` events via the ESPHome
`homeassistant.event:` YAML action, guarded by an `if:` / `condition:` block. The
architecture (`architecture.md`) mandated the opposite: a single-lambda direct
internal-API call (`api::global_api_server->send_homeassistant_action`), and explicitly
listed `homeassistant.event:` on the gateway as an anti-pattern.

On 2026-06-02, Alberto decided to **keep the `homeassistant.event:` YAML action** for the
PoC: it is documented and stable across ESPHome versions, and matches the project's
`on_frame` guard convention. The internal API is undocumented and version-coupled. The
firmware and stories 3-2/3-3 already reflect the kept approach, leaving `architecture.md`
as the sole contradicting artifact.

## 2. Impact Analysis

- **Architecture:** 8 passages updated (lines ~132, 153-162, 245, 303-334, 409-410, 416 [deleted], 518, 559, 579, 612). The "no globals for event staging" principle is **unchanged** — only the firing mechanism and guard placement changed.
- **Epics / Stories:** No rework. Stories 3-2 and 3-3 already authored to the kept approach; epics.md 3-3 byte positions already corrected.
- **PRD:** No change (FR-6 is mechanism-agnostic).
- **Code:** No change (firmware already implements the kept approach).

## 3. Recommended Approach

**Direct Adjustment** — edit `architecture.md` to record the decision and align the doc
with the firmware. No rollback, no replan.

## 4. Detailed Change Proposals (applied)

| # | Location | Change |
|---|----------|--------|
| A | Critical Decisions (~L132) | "Single-lambda HA event firing" → "HA event firing via `homeassistant.event:` YAML action, no global staging" |
| B | Protocol & State Management (L153-162) | Rewrote "Global staging: eliminated" para to describe `homeassistant.event:` + `if:`/`condition:`; added dated reversal rationale |
| C | Cross-component dependencies (L245) | Removed internal-API version re-validation requirement; YAML action is documented/stable |
| D | Gateway on_frame Handler Pattern (L303-334) | Rewrote heading prose + code block to `if:`/`condition:` guard + `homeassistant.event:` action |
| E | Enforcement rules (L409-410) | Generalized guard-placement rule (node vs gateway); updated gateway rule to YAML action |
| F | Anti-patterns (L416) | Deleted the "homeassistant.event used on gateway" anti-pattern (line 419 still covers globals-for-staging) |
| G | FR-6 traceability (L579) | "Single-lambda direct API call" → "`homeassistant.event:` action in `gateway.yaml` on_frame" |
| H | Data-flow diagram + coherence + open-items (L515-518, L559, L612) | Updated to reflect `homeassistant.event:` action |

## 5. Implementation Handoff

**Minor** — applied directly to `architecture.md`; no downstream agent required.

Two intentional historical notes remain in `architecture.md` (the decision-reversal
record at L153-162 and the open-items note at L612) — these are deliberate, not residual
contradictions.

A project memory was recorded: `project_gateway_ha_event_firing_approach` (firmware is the
source of truth on this point until/unless the decision changes again).

## 6. Next Steps

- Ready to implement: `dev-story` for 3-2, then 3-3 (both `ready-for-dev`).
- Hardware verification (button → HA Developer Tools) is deferred to Epic 4 / Story 4.1 bench assembly.
