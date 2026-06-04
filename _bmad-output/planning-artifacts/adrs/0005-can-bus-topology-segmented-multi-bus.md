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

**Proposed.** Two decisions are made: **(1)** the bus is **segmented** (a single bus is not
viable — below), and **(2)** the coupling method is **software bridges** (store-and-forward).
**Segment count and bit rate remain open**, pending a cable-budget/zone sketch (see open
items).

**Governing criterion: reliability** (not cost or firmware effort — Alberto is comfortable
writing firmware; the system must be dependable as always-on house infrastructure). The
software-bridge choice therefore comes with mandatory reliability requirements (see Decision).

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

**Coupling method — DECIDED: software bridges** (store-and-forward, ESP32-class — e.g.
LilyGO T-2CAN or ESP32 + 2× MCP2515). Chosen over controller-as-hub because it keeps the
critical controller **simple and redundancy-able** (ADR-0003) and makes each coupler
failure **partial** (one zone), and because it does not require the star geometry the hub
demands. The choice does not affect the protocol (ADR-0001) or the control model (ADR-0003);
it is a physical-layer decision. (See [candidates ranked on reliability](#coupling-method-candidates--ranked-on-reliability)
for why CAN-Ethernet, plain repeaters, and hub were not chosen.)

Because reliability is the governing criterion and a software bridge's weak point is its
active MCU/firmware, the choice carries **mandatory reliability requirements**:

- **Single-purpose firmware** — the bridge only forwards; no node/actuator roles mixed in.
- **Radios off** — disable WiFi/BT on the bridge MCU (the WiFi stack is a common source of
  heap/stack instability); the bridge lives on CAN only.
- **Hardware watchdog + brownout protection**, and **fail-safe on fault** — on any hang/
  reset the bridge must come up clean and **never babble** (never hold a segment dominant or
  emit garbage). A crashed bridge must degrade to "silent" (one zone's inputs lost), not to
  "disrupts a segment."
- **Clean, adequate power** to each bridge (likely a power rail run alongside CAN).
- **Conservative forwarding** — buffer bursts without dropping; loop-free tree only.

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

### Coupling-method candidates — ranked on reliability

Reliability decomposes into three sub-dimensions that pull differently: **fault
containment** (does a segment fault stay local?), **blast radius** (what dies when the
coupler fails?), and **component MTBF** (the coupler's own dependability).

| Method | Fault containment | Coupler-failure blast radius | Component MTBF |
|---|---|---|---|
| **Plain layer-1 repeater** | ❌ poor — repeats a stuck-dominant/babbling fault to *all* segments (one logical bus); also CAN bit-timing limits how many can chain | one segment | ★★★ (no firmware) |
| **Fault-isolating star coupler** (premium repeater) | ✅ auto-disconnects a faulted segment | one segment | ★★★ (no firmware) |
| **Software bridge** (LilyGO T-2CAN, or ESP32 + 2× MCP2515) | ✅ store-and-forward — a bus-off on one segment stops forwarding; others unaffected; can filter; independent timing domains (scales to deep trees) | one segment (partial) | ★★ — active MCU + firmware; engineerable (watchdog, brownout, **no WiFi**, clean power) |
| **Controller-as-hub** (independent isolated CAN ports) | ✅ each segment on its own controller chip; a fault drops only that port | **no new device** — but loads the critical controller | ★★ — ties to the controller |
| **CAN↔Ethernet gateway** | ✅ | one segment | ★★ **+ depends on the whole LAN** |

**Reliability conclusions:**

- **CAN↔Ethernet — eliminated.** Routes inputs through switches/router/TCP — the fragile
  overlay this architecture deliberately demotes. Worst reliability for this role.
- **Plain repeater — weak.** Highest silicon MTBF but **does not contain** a babbling/
  stuck-dominant fault (it repeats it everywhere). Only a **fault-isolating star coupler**
  recovers containment — at premium cost.
- **Software bridge** and **controller-as-hub** are the two genuinely strong options: both
  contain faults and keep a failure *partial* (one zone). They differ on one axis —
  - *Software bridge* keeps the critical controller **simple** (easier to cold-spare /
    active-standby per ADR-0003), at the cost of N separate active devices (each a
    partial-failure point, engineered to industrial spec).
  - *Controller-as-hub* adds **no separate devices** (fewest failure points) and contains
    per port, but **complicates the one board you most want simple/redundant** and forces a
    **star geometry** (every segment home-runs to the controller).

**Lean (reliability-first):** the choice is between **software bridge** and
**controller-as-hub**, and the **tiebreaker is geometry**, not electronics — if all zones
can home-run to the controller, the hub (with isolated per-port transceivers) is the most
reliable (fewest parts, full containment, no firmware-bearing middleboxes); if they cannot,
software bridges engineered to industrial spec keep each failure partial and the controller
simple. A plain repeater is chosen only to insist on no-firmware silicon, and then it should
be a fault-isolating star coupler.

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
1. **Cable-budget / zone sketch** — number of segments, approximate runs, where they
   converge. Now sets the **segment/bridge count** (the *method* is decided), and the bit-rate.
2. **Bridge firmware platform** — minimal/stripped ESPHome (one toolchain, `on_frame` →
   `send_data`) vs lean custom firmware for a pure-forwarder. Lean toward whichever is
   easiest to make demonstrably fail-safe; radios off either way.
3. **Bit rate** — confirm 125 kbps (or drop to 50 kbps for more headroom) per segment.
4. **Forwarding rules** — start with **forward-all both ways** (simplest, most reliable;
   the controller needs all node traffic and management must reach every segment). Add
   selective filtering only if backbone load ever demands it.
5. **Per-bridge power** — likely a power rail alongside CAN; size for reliability.
6. **Bridge reliability validation** — soak-test the watchdog/fail-safe behavior (a hung
   bridge must go silent, never babble).
7. **Re-verify pricing** at purchase (see caveat) — secondary, since reliability governs.

## Alternatives considered
- **Single trunk-and-spur (one bus).** Simplest, no couplers — **rejected, not viable**
  for this house's layout per Alberto.
- **Controller-as-hub / plain repeater / fault-isolating star coupler / CAN-Ethernet** —
  evaluated on reliability (table above) and **not chosen**: CAN-Ethernet depends on the
  fragile LAN; plain repeaters don't contain babbling faults; hub complicates the critical
  controller and forces star geometry. Hub remains the natural fallback *if* a future layout
  turns out to home-run all zones to the controller.

## Notes
This ADR covers **CAN bus segmentation/coupling** only. Broader physical/electrical
topology (relay placement, mains circuits) remains a separate concern. Depends on ADR-0001
(segment-agnostic IDs) and ADR-0003 (the controller that every segment must reach).
