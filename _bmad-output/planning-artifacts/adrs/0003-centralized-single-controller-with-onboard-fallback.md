---
adr: 0003
title: 'Centralized single-controller with on-board fallback logic (HA-offline graceful degradation)'
status: 'Proposed'
date: '2026-06-04'
deciders: ['Alberto']
author: 'Winston (System Architect)'
dependsOn:
  - 'ADR-0001: Adopt CAN Extended IDs with location-as-address'
relatedDocuments:
  - _bmad-output/planning-artifacts/adrs/0001-can-extended-id-location-as-address.md
  - _bmad-output/planning-artifacts/adrs/0002-runtime-assignable-node-addressing-and-commissioning.md
  - _bmad-output/planning-artifacts/architecture.md
---

# ADR-0003: Centralized single-controller with on-board fallback logic

## Status

**Proposed** — Alberto selected this option (Option 1) on 2026-06-04 after evaluating it
against two distributed alternatives (below); pending formal acceptance and resolution of
the open items. This is the **post-POC target architecture**: the POC's single-gateway
setup was a deliberate simplification that was built and verified; this ADR records what
comes after it.

The physical/electrical **topology** (where relays and circuits live) is explicitly
**out of scope** here and parked for a future ADR at Alberto's request.

## Context

The POC routed everything through a single gateway with all logic in Home Assistant. The
target system must:

- be **resilient to Home Assistant being offline** — lights must still switch; and
- when HA is **online**, let HA handle lighting richly (dimming, colour, scenes, complex
  automations), including Zigbee/Thread fixtures HA owns.

We explored a spectrum from fully distributed (every actuator independently HA-connected)
to fully centralized. The distributed designs delivered fine-grained partial-failure
resilience but dragged in a class of hard problems — HA-event **de-duplication**,
single-**bridge designation**, **per-board liveness divergence**, and **distributed binding
distribution**. The complexity itself is a reliability liability for a home-scale system.

Two facts simplify the physical picture:

- **Inputs are CAN-only.** Buttons are cheap CAN nodes broadcasting events on the bus
  (ADR-0001 Extended-ID INPUT frames as pub/sub subjects). Actuator-board DIs are unused.
- **Relays need not be co-located with the controller.** Modbus/RS485 relay modules can be
  placed remotely, so "centralized controller" does **not** force "all relays in one box."

## Decision

Adopt a **single controller board** (CAN + Ethernet + Modbus) that owns lighting control,
with the button→action logic held **on the board itself** so it survives HA outages.

1. **One controller board** listens to CAN button events, bridges to HA over Ethernet
   (Native API), and drives relays over **Modbus** (relay banks expandable and remoteable
   over RS485). It subsumes the POC "gateway" role.
2. **Logic lives on the board** (ESPHome), not delegated to HA. This is the load-bearing
   condition for the resilience goal.
3. **Per-binding Model-A arbitration**, gated by the board's own `api.connected`:
   - `api.connected` → the board forwards the event to HA; **HA drives** the relay entities
     (and Zigbee/Thread fixtures) — the rich path.
   - `!api.connected` → the board's **local** mapping writes the Modbus relay directly —
     the fallback path.
   - Relays are ESPHome `switch` entities backed by Modbus, so HA (online) and the board's
     local logic (offline) drive the *same* outputs; one gate, one board, **no
     de-duplication and no double-action by construction.**
4. **Zigbee/Thread fixtures are HA-only** — inherently HA-dependent, no local fallback
   (HA down = those fixtures don't respond; relay-backed lights degrade to on/off).
5. **Single source of truth → both views.** The button→action mapping is authored once and
   compiled into (a) the board's on-board fallback logic and (b) HA's automations, so
   online and offline behaviour cannot silently diverge.

### Resilience model

| Failure | Behaviour |
|---|---|
| HA offline | board's local logic drives relays — **basic switching works** |
| Controller board dies | **all relay switching frozen** until the board is restored (the accepted cost) |
| CAN bus fault | the one irreducible shared dependency (true of every option) |

The single board is **consciously load-bearing** for all switching — a deliberate reversal
of the earlier "gateway never load-bearing" stance, traded for a large reduction in standing
complexity. Mitigations: a **cold spare** during build/early operation, and a clean
**active/standby pair** as a future hardening step (a single, well-understood redundancy
mechanism — far simpler than distributed election; see open items).

### Transport roles

- **CAN** — event-driven inputs (button pub/sub, ADR-0001 Extended IDs), node heartbeats,
  and management/commissioning. The `OUTPUT` category stays **management-only** (no live
  relay control on CAN; relays are Modbus + API).
- **Modbus/RS485** — commanded relay outputs; expandable and physically remoteable.
- **Ethernet / Native API** — the controller ↔ HA rich-control channel.

Each bus is used where its communication model fits: CAN is event-driven (instant transmit
on press, arbitrated); Modbus is master-commanded (controller writes a relay on demand).

## Consequences

### Positive

- **Lowest complexity of the options** — one brain, one liveness, one config; no beacon,
  no dedup, no bridge designation, no distributed binding tables, no per-board liveness
  divergence.
- **Predictable failure semantics** — "board up → everything works; board down → nothing
  switches" is far easier to reason about and diagnose than distributed partial failures.
- **Meets the resilience requirement** via on-board logic (condition #2), while preserving
  full HA richness online.
- **Flexible relay placement** via Modbus remoting, despite logical centralization.
- **Clean redundancy path** — future active/standby is one mechanism, not N.

### Negative / costs

- **Single point of failure for all switching.** Board death freezes every relay-controlled
  light until restored. Accepted; mitigated by cold spare now, active/standby later.
- **Modbus is master-polled** with a practical ceiling on relay count / write latency —
  ample at home scale but to be validated (open item).
- **Active/standby introduces a Modbus single-master hand-over problem** (the standby must
  stay passive until failover to avoid bus contention) — deferred with the redundancy work.
- Reverses the non-load-bearing assumption (consciously).

### Open items

1. **On-board binding/logic representation** — how the button→relay mapping is expressed in
   the controller's ESPHome config (the "dumb match" engine), and the per-binding authority
   (local-authoritative vs HA-with-fallback).
2. **Binding lifecycle** — Phase 1 (now): static, compiled, manual reflash through
   build/test. Phase 2 (pre-go-live): bindings runtime-pushed to the controller **over its
   own Native API/Ethernet** (not over CAN — bindings live on one board, so there is no
   distributed commissioning to do). Confirmed phasing; Phase 2 not built yet.
3. **Active/standby redundancy** — design the pair + Modbus-master hand-over. Future.
4. **Modbus scale/latency validation** on target hardware.
5. **Controller board selection** — a board with CAN + Ethernet + Modbus (RS485).
6. **Physical/electrical topology** — parked for its own future ADR (Alberto).

## Alternatives considered

- **Option 2 — Dedicated HA-bridge + distributed CAN actuators.** One dedicated bridge
  board (single HA reporter + liveness beacon + CAN command relay) with cheap CAN-only
  actuators running local fallback bindings. *Best failure behaviour of the three* — no
  single board death costs basic switching (bridge failure degrades soft). **Rejected** for
  now because it re-incurs the liveness beacon, distributed binding tables, and CAN-borne
  relay commands; its built-in resilience can be matched by Option 1 + a future
  active/standby pair at lower standing complexity. Retained as the natural fallback if the
  single-controller blast radius proves unacceptable.
- **Option 3 — Fully distributed, per-board API.** Every actuator independently
  HA-connected; finest-grained partial failure. **Rejected** as dominated — it requires the
  full dedup/bridge-designation machinery and suffers per-board liveness divergence
  (the bridge-SPOF edge), for resilience Option 2 already provides more simply.
- **Pure centralized, logic in HA (no on-board fallback).** **Rejected** outright — fails
  the HA-offline resilience requirement (dark house when HA is down).

## Notes

Builds on ADR-0001 (Extended-ID button events are the CAN pub/sub subjects; the `OUTPUT`
category is management-only) and ADR-0002 (which this ADR rescopes to commissioning of the
CAN-only button nodes only — bindings are *not* commissioned over CAN; they live on this
controller and are pushed over its API). A separate future ADR will cover
physical/electrical topology.
