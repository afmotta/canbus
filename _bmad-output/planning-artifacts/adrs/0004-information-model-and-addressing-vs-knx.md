---
adr: 0004
title: 'Information model & addressing reviewed against KNX (resolution of the two-container critique)'
status: 'Accepted'
date: '2026-06-04'
acceptedDate: '2026-06-10'
deciders: ['Alberto']
author: 'Winston (System Architect)'
dependsOn:
  - 'ADR-0002: Runtime-assignable node addressing and commissioning'
  - 'ADR-0003: Centralized single-controller with on-board fallback logic'
  - 'ADR-0007: Flat node_id identity with central meaning map (supersedes the original ADR-0001 premise)'
relatedDocuments:
  - _bmad-output/planning-artifacts/adrs/0001-can-extended-id-location-as-address.md
  - _bmad-output/planning-artifacts/adrs/0002-runtime-assignable-node-addressing-and-commissioning.md
  - _bmad-output/planning-artifacts/adrs/0003-centralized-single-controller-with-onboard-fallback.md
  - _bmad-output/planning-artifacts/adrs/0006-sensor-data-transport-over-can.md
  - _bmad-output/planning-artifacts/adrs/0007-flat-node-id-with-central-meaning-map.md
  - _bmad-output/planning-artifacts/architecture.md
  - firmware/protocol/canbus_protocol.h
---

# ADR-0004: Information model & addressing reviewed against KNX

## Status

**Accepted (2026-06-10) — revised by ADR-0007 (2026-06-06).** Under the flat-`node_id` model (Extended IDs,
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
| **A** | KNX dual-address split: immutable physical id + assignable logical address | **Adopted — finalized under ADR-0007.** The immutable address is now the flashed `node_id`; logical meaning/function lives in the controller's central map. ADR-0002 established the split in commissioning terms, and ADR-0007 fixed the final wire model. | ADR-0002 + ADR-0007 |
| **B** | "Thin ID, fat payload" — move `button`/`event` out of the ID into the payload | **Adopted under ADR-0007.** `button`/`event` live in the payload while the ID low bits stay reserved until a concrete hardware-filtering consumer exists. | this ADR + ADR-0007 |
| **C** | A functional/group-address layer on the bus (KNX-style) | **Rejected.** The controller's central meaning map provides the function indirection; there is still no separate on-bus group namespace. | ADR-0003 + ADR-0007 |
| **D** | DPT-style typed payloads | **Not adopted (mooted).** See decision below. | this ADR |
| **E** | Local fast-path bindings for resilience | **Adopted** — on-board fallback logic; basic switching survives HA offline. | ADR-0003 |

### The over-arching point: locus of control

The critique argued the container question was *downstream of an unexamined decision* —
centralized vs distributed control. That decision has since been made explicitly:
**centralized single controller with on-board fallback** (ADR-0003). The two-container usage
is therefore judged *in that context*, where it is sound: the **ID carries stable transport
metadata** (`category + node_id`, which is filterable and arbitration-relevant), and the
**payload carries the mutable message detail** (button index, event type, sensor type/value,
heartbeat fields).

### New micro-decisions made here

**D1 — Under the flat `node_id` model, `button`/`event` live in the payload (Hypothesis B adopted in revised form).**
ADR-0007 changed the transport layout: the low 12 ID bits stay reserved, and `button`/`event`
move into the payload. That is the right trade under the current architecture: route on stable
identity (`node_id`) and message class (`category`), keep mutable event detail in the payload,
and consume low ID bits only if a concrete hardware-filtering need appears in the future.

**D2 — No typed-payload (DPT) scheme now; revisit only if CAN message types proliferate.**
Centralization (ADR-0003) shrank the CAN message set to button-events, heartbeats, and
management frames. Relay/light *state* lives in ESPHome entities and Modbus, **not** in CAN
payloads, so the "growing payload zoo" that would justify a DPT-like registry never
materialises. Decision: keep ad-hoc per-message payloads. **Revisit trigger:** if new
device classes ever add several value-carrying CAN message types.

**Follow-up 2026-06-05:** ADR-0006 is exactly this revisit trigger. If ADR-0006 is
accepted, D2 is resolved by its light typed-payload scheme for `CAT_SENSOR`: the ID carries
`CAT_SENSOR + node_id`, while `measurement_type` and status/value remain in the payload.

**D3 — Accept the `node_id` / arbitration-priority coupling as a known, benign limitation.**
Because the ID is `[category:4][node_id:13][reserved:12]`, within a category a lower `node_id`
wins CAN arbitration. Decision: **accept, no change.**
- The *deliberate* priority — the **category** (`SYSTEM > INPUT > OUTPUT > STATUS`) — is
  correctly placed and is the priority that matters.
- The accidental `node_id` ordering is harmless at this scale: button traffic is human-paced
  and effectively never contends within a ~1 ms frame window at 125 kbps; an arbitration loser
  simply retransmits. Sustained-load starvation cannot arise from this traffic profile.
- There is no need to spend the reserved low bits on a separate priority sub-field at this
  scale, and no current consumer could exploit it.
- This is consciously decided **before LIVE** (architecture.md:75 notes CAN-ID priority
  cannot be retrofitted after protocol freeze), so it is an accepted trade, not a drift.

## Consequences

- The KNX critique is now **closed and traceable** — each hypothesis maps to a decision.
- No new firmware or wire-layout change results from accepting this ADR: A/C/E were already
  realised; B and D now record
  the flat `node_id` status quo implemented by ADR-0007; D3 accepts an existing property.
- `architecture.md:75`'s note on arbitration priority is **resolved** for this protocol and
  now points at decision **D3**.

### Open items

1. If ADR-0006 is accepted, annotate D2 as resolved by ADR-0006's light typed-payload
  scheme; otherwise revisit **D2** only on the stated trigger.

## Notes

This ADR is deliberately a *meta/record* ADR. Accepting it changes no design; it records the
remaining micro-decisions and traceability after ADR-0007 so a future reader who finds the KNX
question does not conclude it was dropped. The broader architectural decisions live in
ADR-0002 (commissioning split), ADR-0003 (locus of control & resilience), and ADR-0007
(flat `node_id` identity + wire layout).
