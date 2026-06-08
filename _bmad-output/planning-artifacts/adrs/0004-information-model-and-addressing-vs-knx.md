---
adr: 0004
title: 'Information model & addressing reviewed against KNX (resolution of the two-container critique)'
status: 'Proposed'
date: '2026-06-04'
deciders: ['Alberto']
author: 'Winston (System Architect)'
dependsOn:
  - 'ADR-0001: Adopt CAN Extended IDs with location-as-address'
relatedDocuments:
  - _bmad-output/planning-artifacts/adrs/0001-can-extended-id-location-as-address.md
  - _bmad-output/planning-artifacts/adrs/0002-runtime-assignable-node-addressing-and-commissioning.md
  - _bmad-output/planning-artifacts/adrs/0003-centralized-single-controller-with-onboard-fallback.md
  - _bmad-output/planning-artifacts/architecture.md
  - firmware/common/canbus_protocol.h
---

# ADR-0004: Information model & addressing reviewed against KNX

## Status

**Proposed — revised by ADR-0007 (2026-06-06).** Under the flat-`node_id` model (Extended IDs,
`[category:4][node_id:13][reserved:12]`): **D1 is set to payload** — `button`/`event` live **in
the payload**, because the ID's low bits stay *reserved* (no consumer hardware-filters on them
yet); they move into the ID only when one does. **D3** priority sub-ordering is by `node_id`
within a category. The ADR's *core* conclusion strengthens: the KNX individual-address +
central-map model (Hypothesis A) is now fully adopted (`node_id` = individual address; central
map = function). The rest stands.

This ADR is a **consolidating record**: it does not introduce a new architecture, it closes out
a critique whose conclusions are otherwise scattered across ADR-0001/0002/0003, and it makes the
few micro-decisions that were never explicitly recorded.

## Context

During design, Alberto posed a devil's-advocate question:

> *"Comparing to a market solution like KNX, are we using the two information containers —
> CAN ID and payload — in the right way? Analyse alternatives we didn't think about and
> render them as hypotheses."*

The analysis produced a critique and five hypotheses. Subsequent decisions (the move to a
distributed control model, then the choice of a centralized single controller) **answered
most of them** — but no record tied those answers back to the question, so it appeared
unaddressed. This ADR supplies that traceability.

### The KNX yardstick (summary)

KNX separates four semantic slots: an immutable **individual address** (physical, for
management), an assignable **group address** (the *function* — what telegrams are addressed
to, pub/sub), an explicit **APCI verb** (read/write/response), and a **DPT-typed payload**
(self-describing values). The core lesson: *route on the stable function, keep mutable
detail and values in the payload, and separate physical identity from logical function.*

## Decision

Record the disposition of every point from the critique. Where a decision already exists,
cite it; where one was missing, make it here.

### Hypotheses — disposition

| # | Hypothesis | Disposition | Recorded in |
|---|---|---|---|
| **A** | KNX dual-address split: immutable physical id + assignable logical address | **Adopted** — `hwid` (physical, commissioning handle) + `room/board` (logical, operational). We deliberately embraced the split the critique said we were half-reinventing. | ADR-0002 |
| **B** | "Thin ID, fat payload" — move `button`/`event` out of the ID into the payload | **Rejected; keep them in the ID.** See decision below. | this ADR + ADR-0001 |
| **C** | A functional/group-address layer on the bus (KNX-style) | **Rejected.** Button identity `(room,board,button,event)` is itself the pub/sub subject; the single controller's binding table provides the function indirection. A separate group namespace would be unused generality. | ADR-0003 |
| **D** | DPT-style typed payloads | **Not adopted (mooted).** See decision below. | this ADR |
| **E** | Local fast-path bindings for resilience | **Adopted** — on-board fallback logic; basic switching survives HA offline. | ADR-0003 |

### The over-arching point: locus of control

The critique argued the container question was *downstream of an unexamined decision* —
centralized vs distributed control. That decision has since been made explicitly:
**centralized single controller with on-board fallback** (ADR-0003). The two-container usage
is therefore judged *in that context*, where it is sound: the **ID is the pub/sub subject**
(source identity + event class — legitimately broadcast-filterable), and the **payload
carries values** (near-empty for buttons; simple for heartbeats).

### New micro-decisions made here

**D1 — `button`/`event` stay in the Extended ID (rejects Hypothesis B).**
Putting them in the ID was originally justified by trace readability and gateway-side
filtering. The shift to a pub/sub model **strengthens** that choice: an actuator/controller
filters precisely on the events it binds to, straight from the ID, without parsing payloads.
The "thin ID / fat payload" middle option is recorded as considered and rejected. (Already
implemented under ADR-0001; this records the rationale.)

**D2 — No typed-payload (DPT) scheme now; revisit only if CAN message types proliferate.**
Centralization (ADR-0003) shrank the CAN message set to button-events, heartbeats, and
management frames. Relay/light *state* lives in ESPHome entities and Modbus, **not** in CAN
payloads, so the "growing payload zoo" that would justify a DPT-like registry never
materialises. Decision: keep ad-hoc per-message payloads. **Revisit trigger:** if new
device classes ever add several value-carrying CAN message types.

**Follow-up 2026-06-05:** ADR-0006 is exactly this revisit trigger. If ADR-0006 is
accepted, D2 is resolved by its light typed-payload scheme for `CAT_SENSOR`: measurement
type in the ID, fixed status/value payload encoding, no heavy DPT registry.

**D3 — Accept the room-number / arbitration-priority coupling as a known, benign limitation.**
Because the ID is `[category:3][room:8][board:8]…`, within a category a lower room number
wins CAN arbitration. Decision: **accept, no change.**
- The *deliberate* priority — the **category** (`SYSTEM > INPUT > OUTPUT > STATUS`) — is
  correctly placed and is the priority that matters.
- The accidental room-ordering is harmless at this scale: button traffic is human-paced and
  effectively never contends within a ~1 ms frame window at 125 kbps; an arbitration loser
  simply retransmits. Sustained-load starvation cannot arise from this traffic profile.
- There is no spare ID room for a separate priority field (29 bits are fully allocated), and
  none is needed.
- This is consciously decided **before LIVE** (architecture.md:75 notes CAN-ID priority
  cannot be retrofitted after protocol freeze), so it is an accepted trade, not a drift.

## Consequences

- The KNX critique is now **closed and traceable** — each hypothesis maps to a decision.
- No code or layout change results: A/C/E were already realised; B and D confirm the status
  quo; D3 accepts an existing property.
- `architecture.md:75`'s open note on arbitration priority is **resolved** for this protocol
  (accepted as-is) and can be annotated accordingly.

### Open items

1. Annotate `architecture.md:75` to point at decision **D3** (priority-coupling accepted).
2. If ADR-0006 is accepted, annotate D2 as resolved by ADR-0006's light typed-payload
  scheme; otherwise revisit **D2** only on the stated trigger.

## Notes

This ADR is deliberately a *meta/record* ADR. It changes no design; it exists so that a
future reader who finds the KNX question does not conclude it was dropped. The substantive
decisions live in ADR-0001 (ID layout), ADR-0002 (physical/logical split & commissioning),
and ADR-0003 (locus of control & resilience).
