---
title: 'Approve ADR-0004 and align its follow-up artifacts'
type: 'chore'
created: '2026-06-10'
baseline_commit: '1a56f4927b7cc850fe2088f2a6af19d0132d06be'
status: 'done'
context:
  - '{project-root}/_bmad-output/project-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/adrs/0004-information-model-and-addressing-vs-knx.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture.md'
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** ADR-0004 already captures the final disposition of the KNX comparison and states that no protocol redesign is required, but it is still marked Proposed and the architecture document still presents the arbitration-priority concern as open. That leaves the planning artifacts inconsistent with the actual decisions already reflected elsewhere in the repo.

**Approach:** Formally accept ADR-0004 using the same metadata pattern as the repo's other accepted ADRs, then update the architecture note it explicitly calls out so the remaining follow-up is closed in the planning set. Treat this as a documentation-alignment change unless validation shows a real contradiction with the current flat `node_id` model.

## Boundaries & Constraints

**Always:** Preserve ADR-0004's current technical substance; use the existing accepted-ADR frontmatter convention already present in ADR-0003 and ADR-0007; keep the change set focused on artifacts needed to make ADR-0004's approval traceable; verify that the current firmware and protocol documentation already align with the flat `node_id` model before deciding no code change is needed.

**Ask First:** If review finds any current source or planning artifact that still describes room/board addressing as the active wire model; if the only honest way to resolve the request would require changing firmware or protocol files; if Alberto wants ADR-0006's typed-payload follow-up folded into this change instead of keeping ADR-0004 approval narrow.

**Never:** Do not redesign CAN ID layout, payload semantics, or arbitration rules; do not reopen the already-decided ADR-0007 flat `node_id` model; do not expand this task into a general cleanup of old ADRs, architecture notes, or implementation artifacts unrelated to ADR-0004's explicit open items.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Approval path | ADR-0004 is still `Proposed`, and the architecture topology note still reads like an unresolved concern | ADR-0004 becomes `Accepted` with an `acceptedDate`, and the architecture note points to ADR-0004 D3 as the accepted resolution | N/A |
| Scope drift found | A current file contradicts ADR-0004's claim that no code or layout change results | Stop before widening the patch set, surface the conflicting file, and renegotiate scope with the human | Do not silently broaden the implementation |

</frozen-after-approval>

## Code Map

- `_bmad-output/planning-artifacts/adrs/0004-information-model-and-addressing-vs-knx.md` -- target ADR whose approval metadata and status text need to reflect the final decision.
- `_bmad-output/planning-artifacts/architecture.md` -- contains the open CAN topology and arbitration note that ADR-0004 says should be annotated as resolved.
- `_bmad-output/planning-artifacts/adrs/0003-centralized-single-controller-with-onboard-fallback.md` -- accepted ADR example used to mirror frontmatter and status-section wording.
- `_bmad-output/planning-artifacts/adrs/0007-flat-node-id-with-central-meaning-map.md` -- accepted ADR example and the active identity model ADR-0004 now references.
- `firmware/protocol/canbus_protocol.h` -- validation-only anchor to confirm the current wire model already matches the approved ADR set and needs no edit.

## Tasks & Acceptance

**Execution:**
- [x] `_bmad-output/planning-artifacts/adrs/0004-information-model-and-addressing-vs-knx.md` -- change frontmatter from `Proposed` to `Accepted`, add `acceptedDate: '2026-06-10'`, and update the status paragraph to read as an accepted consolidating ADR while preserving its ADR-0007 revision note -- formalizes the decision using the repo's established ADR pattern.
- [x] `_bmad-output/planning-artifacts/architecture.md` -- annotate the CAN bus topology and arbitration note so it no longer reads as an unresolved protocol question and instead references ADR-0004 D3 as the accepted rationale -- closes the one explicit follow-up named by ADR-0004.
- [x] `firmware/protocol/canbus_protocol.h` -- inspect for validation only and leave unchanged if it already reflects the flat `node_id` model -- prevents unnecessary protocol churn while still disconfirming the no-code-change hypothesis.

**Acceptance Criteria:**
- Given ADR-0004 is the decision record for the KNX comparison, when its frontmatter and status section are reviewed after the change, then it is clearly marked `Accepted` with acceptance date `2026-06-10` and still reads as a consolidating record rather than a new architecture change.
- Given the architecture document currently flags CAN ID priority as an open concern, when the updated note is read, then it explicitly points to ADR-0004 D3 as the reason the priority-coupling trade is accepted for this protocol.
- Given the repo already operates on the post-ADR-0007 flat `node_id` model, when scope validation is completed, then no firmware or protocol file is modified as part of approving ADR-0004.

## Spec Change Log

## Design Notes

This spec intentionally narrows "implement the relevant changes" to documentation alignment because ADR-0004 itself says no code or layout change results from its conclusions. The cheapest disconfirming check is local: confirm that the architecture note is still unresolved, and confirm that `firmware/protocol/canbus_protocol.h` already speaks in terms of the flat `node_id` model rather than the superseded room and board address model. If either check fails, stop and renegotiate scope instead of improvising broader edits.

## Verification

**Commands:**
- `grep -nE "status: 'Accepted'|acceptedDate" _bmad-output/planning-artifacts/adrs/0004-information-model-and-addressing-vs-knx.md` -- expected: both acceptance markers are present.
- `grep -n "ADR-0004" _bmad-output/planning-artifacts/architecture.md` -- expected: the CAN topology and arbitration note references ADR-0004 as the resolution path.
- `git diff -- _bmad-output/planning-artifacts/adrs/0004-information-model-and-addressing-vs-knx.md _bmad-output/planning-artifacts/architecture.md` -- expected: only the ADR approval metadata and text plus the architecture annotation changed.

**Manual checks (if no CLI):**
- Inspect `firmware/protocol/canbus_protocol.h` and confirm the active comments and constants already describe flat `node_id` addressing; if they do not, stop and reassess scope before implementation.

## Suggested Review Order

**Intent & Acceptance**

- Start from the approved scope and human-owned boundaries.
  [`spec-adr-0004-approve-and-align-artifacts.md:15`](spec-adr-0004-approve-and-align-artifacts.md#L15)

- Check the concrete tasks and the acceptance bar used to judge completion.
  [`spec-adr-0004-approve-and-align-artifacts.md:46`](spec-adr-0004-approve-and-align-artifacts.md#L46)

**ADR Ratification**

- See where ADR-0004 is formally accepted and re-scoped under ADR-0007.
  [`0004-information-model-and-addressing-vs-knx.md:27`](../planning-artifacts/adrs/0004-information-model-and-addressing-vs-knx.md#L27)

- Review the revised D1 rationale for payload-carried event detail.
  [`0004-information-model-and-addressing-vs-knx.md:87`](../planning-artifacts/adrs/0004-information-model-and-addressing-vs-knx.md#L87)

- Review the accepted D3 arbitration trade in its authoritative record.
  [`0004-information-model-and-addressing-vs-knx.md:104`](../planning-artifacts/adrs/0004-information-model-and-addressing-vs-knx.md#L104)

- Confirm the consequences text distinguishes approval from new wire changes.
  [`0004-information-model-and-addressing-vs-knx.md:120`](../planning-artifacts/adrs/0004-information-model-and-addressing-vs-knx.md#L120)

**Architecture Traceability**

- Verify the topology note now separates unresolved topology from accepted priority coupling.
  [`architecture.md:75`](../planning-artifacts/architecture.md#L75)

**Deferred Follow-Up**

- See the pre-existing project-context drift captured for later cleanup.
  [`deferred-work.md:3`](deferred-work.md#L3)