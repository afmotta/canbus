---
adr: 0003
title: 'Centralized single-controller with on-board fallback logic (HA-offline graceful degradation)'
status: 'Accepted'
date: '2026-06-04'
acceptedDate: '2026-06-10'
deciders: ['Alberto']
author: 'Winston (System Architect)'
dependsOn:
  - 'ADR-0007: Flat node_id identity with central meaning map (supersedes the original ADR-0001 dependency)'
relatedDocuments:
  - _bmad-output/planning-artifacts/adrs/0001-can-extended-id-location-as-address.md
  - _bmad-output/planning-artifacts/adrs/0002-runtime-assignable-node-addressing-and-commissioning.md
  - _bmad-output/planning-artifacts/adrs/0007-flat-node-id-with-central-meaning-map.md
  - _bmad-output/planning-artifacts/architecture.md
---

# ADR-0003: Centralized single-controller with on-board fallback logic

## Status

**Accepted (2026-06-10).** Alberto selected this option (Option 1) on 2026-06-04 after
evaluating it against two distributed alternatives (below). This is the **post-POC target
architecture**: the POC's single-gateway setup was a deliberate simplification (since
validated and signed off in Epic 4); this ADR records what comes after it.

Two things changed between proposal and acceptance:

- **ADR-0007** (accepted 2026-06-09) superseded ADR-0001/0002 and re-keyed node identity to
  a flat `node_id`. Binding source events are therefore keyed on `(node_id, button, event)`
  — the controller resolves `node_id → room` via the central map (ADR-0007 §6). This ADR's
  control architecture is otherwise unaffected (ADR-0007 "Impact on other ADRs").
- **Open item 4 (PoC command-surface cleanup) is already resolved**: the generic
  `SUBTYPE_OUTPUT_CMD` / `canbus_send_output` hooks were removed in the ADR-0007 protocol
  rewrite (PRs #12–#19); `CAT_OUTPUT` is management/commissioning-only.

The `ha_ready` arbitration machinery (readiness heartbeat + TTL, manifest-hash check,
per-event ACK/fallback timeout) is prototyped on the current PoC gateway — log-only
fallback, placeholder manifest hash — to resolve open item 2 (timeout values) empirically.

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
3. **Per-binding Model-A arbitration**, gated by the board's own `ha_ready` state, not raw
   `api.connected`:
   - `ha_ready` → the board forwards the event to HA; **HA drives** the relay entities
     (and Zigbee/Thread fixtures) — the rich path.
   - `!ha_ready` → the board's **local** mapping writes the Modbus relay directly — the
     fallback path.
   - Relays are ESPHome `switch` entities backed by Modbus, so HA (online) and the board's
     local logic (offline) drive the *same* outputs; one gate, one board, **no
     de-duplication and no double-action by construction.**
4. **Zigbee/Thread fixtures are HA-only** — inherently HA-dependent, no local fallback
   (HA down = those fixtures don't respond; relay-backed lights degrade to on/off).
5. **Single source of truth → both views.** The button→action mapping is authored once as a
  canonical binding manifest and compiled/generated into (a) the board's on-board fallback
  logic and (b) HA's automations, so online and offline behaviour cannot silently diverge.

### Binding model and arbitration

The canonical binding manifest is the source of truth. Each binding records:

- source event: `(node_id, button, event)` — flat `node_id` per ADR-0007; the controller
  resolves `node_id → room` via the central map
- `mode`: one of `ha_with_local_fallback`, `local_authoritative`, `ha_only`
- target: Modbus relay/switch, HA entity, scene, or automation reference
- local fallback action, when applicable: e.g. `toggle`, `on`, `off`, `pulse`
- HA action reference / generated automation id
- manifest `version` and `hash`

The controller and HA both carry the same manifest hash. The controller considers HA ready
only when all of these are true:

1. ESPHome Native API is connected.
2. HA has sent a fresh readiness heartbeat within the configured TTL.
3. HA's reported binding manifest hash matches the controller's compiled/current hash.

For `ha_with_local_fallback` bindings, the controller emits the HA event with an `event_id`,
manifest hash, and source tuple. HA's generated automation calls a controller ACK service
after it has accepted/applied the action. If the ACK does not arrive before the fallback
timeout, the controller runs the local fallback action. For `local_authoritative` bindings,
the controller always drives the relay and reports the event to HA; HA must not duplicate
that relay action. For `ha_only` bindings (Zigbee/Thread fixtures, rich scenes without a
relay-backed fallback), the controller reports to HA when ready and does nothing locally
when HA is not ready.

Phase 1 binding lifecycle is static: edit manifest → generate controller config and HA
automations → compile/reflash the controller → load HA automations. A manifest hash mismatch
disables HA authority and uses local fallback where available. Phase 2 keeps the same
manifest/hash model but pushes updates to the controller over its Native API/Ethernet using
staging, commit, rollback, and hash reconciliation; bindings are still not distributed over
CAN.

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

The current PoC firmware still exposes generic `SUBTYPE_OUTPUT_CMD` / `canbus_send_output`
hooks. Those are treated as **PoC-era command hooks**, not target-architecture relay
control. Before implementing this target architecture, generic CAN output commands should be
removed, renamed, or constrained to input-node management use cases (configuration,
identify/diagnostics, factory reset, optional local indicators). Live relay/light actuation
belongs on Modbus/RS485 from the controller.

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

1. ~~**Binding manifest tooling** — choose the manifest file format/location and generator
  outputs for controller ESPHome YAML and HA automations.~~ **Resolved** by **ADR-0009**
  (accepted 2026-06-13): the manifest is `registry/bindings.yaml`, and `generate_nodes.py`
  emits the controller artifacts + HA package, all hash-stamped from one run.
2. **Timeout values** — set HA readiness heartbeat TTL and per-event ACK fallback timeout on
  target hardware so degraded switching remains acceptably fast without causing double
  actions. *In progress:* the machinery is prototyped on the PoC gateway with tunable
  substitutions (`ha_heartbeat_ttl_ms`, `ack_timeout_ms`) so values can be tuned empirically.
3. **Runtime binding push (Phase 2)** — design staging/commit/rollback over the controller's
  Native API/Ethernet. Confirmed not over CAN.
4. **PoC command-surface cleanup** — ~~remove/rename/constrain generic `SUBTYPE_OUTPUT_CMD`
  and `canbus_send_output` before target implementation so `CAT_OUTPUT` is management-only.~~
  **Resolved** by the ADR-0007 protocol rewrite (PRs #12–#19): the hooks are gone and
  `CAT_OUTPUT` is management/commissioning-only.
5. **Active/standby redundancy** — design the pair + Modbus-master hand-over. Future.
6. **Modbus scale/latency validation** on target hardware.
7. **Controller board selection** — a board with CAN + Ethernet + Modbus (RS485).
8. **Physical/electrical topology** — parked for its own future ADR (Alberto).

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
category is management-only) and ADR-0002 (commissioning of CAN endpoint node identity only
— bindings are *not* commissioned over CAN; they live on this controller and are pushed over
its API). A separate future ADR will cover
physical/electrical topology.
