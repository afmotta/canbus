---
adr: 0005
title: 'CAN bus topology: segmented multi-bus with inter-segment coupling'
status: 'Proposed'
date: '2026-06-04'
deciders: ['Alberto']
author: 'Winston (System Architect)'
dependsOn:
  - 'ADR-0001: Adopt CAN Extended IDs with location-as-address'
  - 'ADR-0003: Centralized single-controller with on-board fallback'
relatedDocuments:
  - _bmad-output/planning-artifacts/adrs/0001-can-extended-id-location-as-address.md
  - _bmad-output/planning-artifacts/adrs/0003-centralized-single-controller-with-onboard-fallback.md
  - _bmad-output/planning-artifacts/architecture.md
---

# ADR-0005: CAN bus topology — segmented multi-bus with inter-segment coupling

## Status

**Proposed.** The **segmentation decision is made** (a single bus is not viable — below).
The **coupling method and segment count are open**, pending a cable-budget/zone sketch
(see open items). This ADR records the decision that *is* made and frames the sub-decision
that remains, with the option analysis and indicative pricing to support it.

## Context

CAN is a **linear, terminated** bus (120 Ω at both ends), not a star or free branch
topology. At the project's **125 kbps** it is forgiving — roughly ~500 m total budget and
short (few-metre) stubs — so the realistic single-bus form is a **trunk-and-spur**, not a
strict single-file daisy-chain.

**Alberto has determined that a single trunk-and-spur is *not viable* for this house.** The
physical layout cannot be served by one electrical bus within the budget/stub constraints.
Segmentation is therefore required.

The addressing model helps: ADR-0001 IDs are globally unique `(room, board, …)`, so frames
are **segment-agnostic** — there are no per-segment ID collisions to manage regardless of
how the bus is split.

## Decision

Adopt a **segmented CAN topology**: a **main/backbone bus** plus **secondary buses**
(per zone/floor), joined by **inter-segment coupling devices**, arranged as a strict
**tree (no loops)** — raw CAN has no TTL, so any ring is an unkillable broadcast storm.

The **coupling method is left open** as a sub-decision among the four candidates below,
to be resolved by the segment sketch. The choice does not affect the protocol (ADR-0001)
or the control model (ADR-0003); it is a physical-layer/decision.

### Interaction with ADR-0003 (must hold for any coupling method)

- The single controller (ADR-0003) must **hear all segments**, so couplers must forward
  button events + heartbeats from every secondary toward the controller, and forward
  **management/commissioning** frames (ADR-0002 press-to-assign) back to secondaries.
- A coupler is therefore **load-bearing for its segment's control**: if a secondary's only
  path to the controller fails, that zone's buttons reach neither HA nor on-board fallback
  (the controller is the fallback actuator). This adds **per-segment SPOFs** the single bus
  didn't have — but in exchange, segmentation **isolates faults** (a wiring fault or
  babbling node on one segment no longer kills the whole house). Net: trades "rare *total*
  outage" for "more-frequent *partial* outages + active fault isolation," which is
  generally preferable at home scale. The controller remains the overall total SPOF
  regardless (accepted in ADR-0003).
- Relays live on Modbus at/near the controller (ADR-0003), **not** on CAN segments, so a
  coupler failure cuts a zone's *inputs*, not its relays (lights hold last state).

### Coupling-method candidates

| Method | What it is | Firmware? | Fault isolation | Notes |
|---|---|---|---|---|
| **Layer-1 repeater** | Electrically extends/retimes the bus; allows branching/star | No | Low (one collision domain) | Plug-and-play, low latency, galvanic isolation; buys *reach*, not isolation/filtering |
| **Software bridge** (e.g. LilyGO T-2CAN, or ESP32 + 2× MCP2515) | Store-and-forward between two segments | **Yes** | High (separate domains; can filter) | Cheapest active option; can run ESPHome; per-segment firmware to keep robust |
| **Controller-as-hub** | Multiple CAN interfaces on the controller; segments are spokes | Integrate in ESPHome | High | No separate devices; cheapest in parts; **requires all segments to physically reach the controller** |
| **CAN↔Ethernet gateway** | Each segment gatewayed to the LAN the controller already has | No (configured) | High | Good when zones are far-flung with existing Ethernet; reintroduces Ethernet (switches) into the input path |

### Indicative pricing (per segment/coupler)

> **Caveat — read before quoting these.** Prices are **indicative, ~June 2026**, and
> **must be verified at purchase**. Vendor/marketplace pages block automated retrieval, and
> search-engine price summaries proved unreliable during this analysis (the Copperhill
> figure below was corrected from a bad ~$30–50 search summary to the **$118** Alberto
> observed on the vendor site). Treat these as order-of-magnitude tiers, not quotes.

| Option | Indicative price | Confidence |
|---|---|---|
| Controller-as-hub — MCP2515 per CAN port | ~$3–5 / port | med (component price) |
| DIY software bridge — ESP32 + 2× MCP2515 | ~$12–20 / segment | med |
| Software bridge — LilyGO T-2CAN | ~$33–35 / segment | med (2 retailers agreed) |
| Generic isolated CAN module (AliExpress/eBay) | ~$40–60 / segment | low (quality varies; may be repeater *or* bridge) |
| CAN↔Ethernet gateway (Waveshare / PUSR class) | ~$50–90 / segment | low (estimate) |
| Industrial DIN repeater — Copperhill CAN-11 | **~$118 / segment** | high (vendor-confirmed) |
| Premium repeater — PEAK PCAN-Repeater (DR) | ~$200+ / segment | low–med |

**Structural takeaway:** "no-firmware reliability" (industrial repeaters, $100–200) costs
roughly **5–10× per segment** more than "write firmware" (controller-hub ~$5, software
bridge ~$15–35). The cheap end is the DIY/firmware end.

## Consequences

### Positive
- Makes the house physically wireable (each segment a short, clean, terminated bus).
- Better per-segment signal integrity and headroom.
- Active **fault isolation** between zones.
- No protocol/addressing change (IDs are segment-agnostic).

### Negative / costs
- **Per-segment SPOF** at each coupler (see ADR-0003 interaction).
- More active devices to power, mount, and (for software bridges) keep firmware-robust.
- Store-and-forward couplers add small latency and must buffer bursts without dropping.
- Strict no-loop discipline required.
- If forwarding is "copy everything," the **main bus carries aggregate traffic** (fine at
  this load); selective forwarding adds bridge complexity.

## Open items
1. **Cable-budget / zone sketch** — number of segments, approximate runs, and where they
   converge. This input *drives* the coupling choice and the unit count/total cost.
2. **Pick the coupling method** from the four candidates, using #1.
3. **Bit rate** — confirm 125 kbps (or drop to 50 kbps for more headroom) per segment.
4. **Forwarding/filtering rules** (if software bridges): what crosses each coupler.
5. **Coupler reliability** — watchdogs / redundancy if a software bridge is chosen.
6. **Re-verify all pricing** at purchase time (see caveat).

## Alternatives considered
- **Single trunk-and-spur (one bus).** Simplest and no couplers, but **rejected — not
  viable** for this house's layout per Alberto.
- The four coupling methods above are *not* alternatives to reject but the **open
  sub-decision** this ADR scopes.

## Notes
This ADR covers **CAN bus segmentation/coupling** only. Broader physical/electrical
topology (relay placement, mains circuits) remains a separate concern. Depends on ADR-0001
(segment-agnostic IDs) and ADR-0003 (the controller that every segment must reach).
