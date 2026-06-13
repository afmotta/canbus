---
adr: 0009
title: 'Central map & binding manifest: git as system of record, schema, generation pipeline, backup/restore, export contract'
status: 'Accepted'
date: '2026-06-11'
acceptedDate: '2026-06-13'
deciders: ['Alberto']
author: 'Winston (System Architect)'
dependsOn:
  - 'ADR-0003: Centralized single-controller with on-board fallback (binding manifest + manifest hash)'
  - 'ADR-0006: Sensor data transport over CAN (HVAC controller reads exported map metadata)'
  - 'ADR-0007: Flat node_id identity with central meaning map (open item 2)'
relatedDocuments:
  - _bmad-output/planning-artifacts/adrs/0003-centralized-single-controller-with-onboard-fallback.md
  - _bmad-output/planning-artifacts/adrs/0006-sensor-data-transport-over-can.md
  - _bmad-output/planning-artifacts/adrs/0007-flat-node-id-with-central-meaning-map.md
  - _bmad-output/planning-artifacts/adrs/0008-post-live-firmware-evolution-no-can-bootloader.md
  - firmware/registry/nodes.csv
  - firmware/protocol/node_map.h
  - firmware/tools/commission.py
  - firmware/tools/allocate_node.py
  - firmware/gateway/gateway.yaml
---

# ADR-0009: Central map & binding manifest — system of record, schema, pipeline, backup

## Status

**Accepted (2026-06-13).** Ratifies the git repository as the system of record for all
meaning — identity, placement, and bindings — with every runtime copy generated, compiled,
and hash-stamped from it. Resolves ADR-0007's last open item (§2: central-map schema,
commissioning service, backup) and ADR-0003's open item 1 (binding-manifest
format/location/tooling). Drafted from the 2026-06-11 gap analysis: the map had **three
consumers pulling on one undecided design** — the commissioning CLI (Phase 1, shipped), the
`ha_ready` arbitration (live, but stubbed with `manifest_hash: "dev-unbound"`), and
ADR-0006's HVAC controller (needs read-only map metadata). Deciding it once here prevents
deciding it three times. First implementation is split: ratification + the binding manifest
(`registry/bindings.yaml`) + the canonical hash that un-stubs the arbitration land first;
the export/visibility layer (`map.json`, the compiled bindings table, the generated HA
package, drift-visibility entities) follows as a tracked slice — see open item 2 and
`_bmad-output/implementation-artifacts/deferred-work.md`.

## Context

ADR-0007 moved all meaning off the nodes and into "a central map" — but deliberately left
its schema, storage, and backup open. What shipped in Phase 1 (PRs #16–#17, #21) created a
de-facto answer without recording it:

- `firmware/registry/nodes.csv` + `node_id_hwm` in **git** hold identity, placement, and
  hardware fit; `generate_nodes.py` compiles them into `node_map.h`, baked into the gateway
  at flash time; `commission.py`/`allocate_node.py` are the only writers. Edits are static:
  edit → regenerate → reflash.
- ADR-0003's binding model adds a second meaning-bearing artifact: fallback bindings
  `(node_id, button, event) → action`, plus a **manifest hash** that HA must echo for
  `ha_ready` — currently a placeholder substitution, which keeps the arbitration prototype
  from being real.
- ADR-0006's HVAC controller "may read exported map metadata for friendly names and
  diagnostics" — an export contract that doesn't exist yet.

One asymmetry drives the whole design: **placements are rebuildable, bindings are not.**
If the map is lost, press-to-identify (ADR-0007) re-derives every node's room in an
afternoon of walking the house. But bindings — which button does what — exist nowhere
except in the manifest; losing it means re-authoring the house's behavior from memory.
Backup is therefore not hygiene; it is the difference between a nuisance and a redesign.

## Decision

Seven parts. The stance in one line: **the git repository is the system of record; every
runtime copy is generated, compiled, and hash-stamped from it; nothing on the bus or in HA
is ever authoritative.**

### 1. System of record: the git repository

`firmware/registry/` in this repo is the single authoritative home of all meaning:
identity, placement, hardware fit, and bindings. The controller carries a *compiled copy*
(`node_map.h`, bindings artifact), HA carries a *generated copy* (automations package),
the HVAC controller carries a *read-only export*. The bus is never authoritative —
press-to-identify is an input *event* that a human turns into a registry edit; no device
state is ever read back as truth. This is configuration-as-code, and it is already the
shipped reality — this ADR makes it load-bearing.

### 2. Schema: two files, one concern each

- **`registry/nodes.csv`** (exists, unchanged): one row per physical board —
  `node_id, floor, room, board, location, sensors`. Identity + placement + hardware fit.
  Stays CSV: the allocate/commission round-trip tooling is shipped and tested, and the
  additive-column migration pattern (the `sensors` migration in `allocate_node.py`) is the
  precedent for future columns. Placement semantics per ADR-0006: a host node's `room` is
  its *sensors'* room — the same-room rule is validated here.
- **`registry/bindings.yaml`** (new): the **binding manifest** — ADR-0003's fallback
  behavior as data. Top-level `schema_version`, then a list of bindings keyed
  `(node_id, button, event)` mapping to a controller-side action (relay channel
  open/close/toggle). YAML, not CSV, because actions are structured and will grow
  parameters (e.g. timers); reviewed by git diff like everything else.

The two files split on a real seam: `nodes.csv` answers *what hardware exists and where it
is*; `bindings.yaml` answers *what the house does*. Commissioning edits the first;
behavior design edits the second.

### 3. Canonical manifest hash (un-stubs the arbitration)

The `manifest_hash` is **SHA-256 over a canonical serialization of `bindings.yaml`**
(parsed structure with sorted keys — not raw file bytes, so formatting and comments don't
change identity), truncated to 16 hex characters. The generator injects the same value
into both sides in the same run: the controller's `manifest_hash` substitution (replacing
`"dev-unbound"`) and the generated HA package that echoes it in the readiness heartbeat.
Both sides derived from one source in one run — agreement by construction, drift
detectable by design (a mismatch keeps `ha_ready` off, which is exactly ADR-0003's intent).

### 4. Generation pipeline: one source, all artifacts

One generator run (`generate_nodes.py`, extended) emits every derived artifact:

| Artifact | Consumer | Exists? |
|---|---|---|
| `nodes/node<id>.yaml` | node firmware build | yes |
| `protocol/node_map.h` | gateway/controller (compile-time) | yes |
| controller fallback-bindings artifact (header or YAML include) | controller firmware | new |
| HA automations/package incl. echoed `manifest_hash` | Home Assistant | new |
| `registry/map.json` (see §7) | HVAC controller, tooling, dashboards | new |

All generated artifacts stay **committed** (existing convention: generated ≠ temporary;
diffs are the review surface). The generator stays stdlib-only Python.

### 5. Edit surface: the CLIs, plus reviewed hand-edits

`allocate_node.py` (identity) and `commission.py` (placement) remain the only writers of
`nodes.csv`. `bindings.yaml` is hand-edited and reviewed via git diff — at house scale a
text file beats a binding UI, and the generator validates every referenced `node_id`
exists and every `(node_id, button, event)` key is unique. **Runtime push stays deferred**
(ADR-0003 open item 3): Phase 1's edit → regenerate → reflash loop remains the only apply
path until the pre-LIVE phase demands better. This ADR fixes the *data model* so that a
future push mechanism transports the same artifacts, not new ones.

### 6. Backup, restore, and drift visibility

- **Backup = the git remote (GitHub).** Nothing else to operate, nothing to forget —
  pushing is already the workflow. Because bindings are unrebuildable (Context), the
  remote stops being a convenience and becomes **critical infrastructure**: registry
  changes must be pushed as part of the commissioning routine, not batched for later.
- **Restore = clone → regenerate → reflash the controller.** No device holds state that
  isn't reproducible from the repo; a dead controller plus a fresh board equals the old
  controller (this is the same stateless-device principle ADR-0007 applied to nodes,
  applied to the controller's config).
- **Drift visibility:** the controller exposes its compiled `manifest_hash` (and the map
  generation timestamp) as read-only HA diagnostic entities. "Committed in git but not yet
  reflashed" — the natural failure mode of a static map — becomes visible on a dashboard
  instead of discovered when a button misbehaves.

### 7. Export contract for read-only consumers

Two stable forms, both generated, both committed:

- **C++ compile-time:** `protocol/node_map.h` *is* the contract for firmware consumers —
  the HVAC controller builds against this repo and includes it like the gateway does. Its
  shape (`NodeMapEntry`, sentinel `0xFF`/"unknown", `node_map_*()` accessors) is now
  frozen-additive: fields may be added, never changed or removed.
- **Everything else:** `registry/map.json` — `schema_version`, generation timestamp,
  `manifest_hash`, and the node list (id, floor, room, board, location, sensors). For
  non-C consumers (dashboards, scripts, the HVAC controller's diagnostics if it prefers
  JSON at build time).

Authority boundaries per ADR-0006 §6 are unchanged: the HVAC controller reads exports; it
never allocates `node_id`s or writes the registry.

## Consequences

### Positive

- **Boring by construction** — CSV + YAML + git + one stdlib generator; no database, no
  custom service, no new runtime component anywhere.
- **The arbitration becomes real** — `"dev-unbound"` is replaced by a hash that actually
  guards binding-version agreement, closing the gap between ADR-0003's design and its
  prototype.
- **Backup is the existing workflow** — git push; restore is a clone. The unrebuildable
  artifact (bindings) is protected by the same mechanism that protects the code.
- **One generator run cannot half-update** — controller hash and HA hash come from the
  same execution; map and bindings artifacts cannot drift from their source unnoticed.
- **Consumers decoupled** — HVAC and future tooling read frozen-additive exports, not
  internal files.

### Negative / costs

- **Reflash-to-apply remains** (Phase 1 carried forward): every placement or binding edit
  costs a controller OTA reflash until runtime push (ADR-0003 item 3) lands. Accepted —
  the controller is OTA-reachable, and edit frequency at house scale is low.
- **Git discipline becomes operational discipline** — an unpushed registry commit is an
  unbacked-up house. Mitigated by folding `git push` into the commissioning runbook, but
  it is a human rule, not a mechanical gate (a pre-LIVE hook could harden it — open item).
- **Hand-edited YAML bindings** have no UI guardrails beyond generator validation; a
  semantically wrong (but valid) binding ships. Accepted at house scale; the git diff is
  the review.
- **`node_map.h` shape freeze** constrains future map fields on firmware consumers to
  additive evolution — consistent with ADR-0008's controller-absorbs-change doctrine.

## Alternatives considered

- **Controller-resident map with runtime edits (map lives on the device, CLI talks to a
  commissioning service).** Rejected: creates device state that must itself be backed up,
  inverts the restore story (repo rebuilt *from* device), and builds the Phase-2 push
  transport now, before it's needed. The chosen design lets a push mechanism layer on
  later without changing where truth lives.
- **Home Assistant as system of record (helpers/storage, HA UI as editor).** Rejected
  outright: HA is the component the architecture explicitly designs to be allowed to fail
  (ADR-0003); the fallback path's own configuration must not live inside it. HA-side
  `.storage` is also opaque to diff/review.
- **Single combined registry file (bindings as more columns/rows in nodes.csv).** Rejected:
  conflates hardware inventory with behavior; bindings need structure CSV can't express
  cleanly; and the manifest hash should cover *behavior only* — placement edits (e.g.
  renaming a location) must not flip `ha_ready`.
- **SQLite / a real database.** Rejected: ~100 rows, single human writer; a database adds
  an operational dependency and removes git-diff reviewability for nothing.

## Open items

1. **Binding action vocabulary** — the action side of `bindings.yaml` (relay channel
   naming, Modbus addressing) is constrained by controller board selection (ADR-0003 open
   item 7). Schema ships with a minimal `relay: <channel>, op: on|off|toggle` form and
   grows additively.
2. **Implementation slices** — `bindings.yaml` + canonical-hash function (natively
   testable, `ha_arbitration.h` pattern); generator extensions (bindings artifact, HA
   package, `map.json`); drift-visibility entities on the controller.
3. **HA package generation details** — automations vs blueprint vs single package file;
   how the echoed hash is wired into the existing ACK service heartbeat.
4. **Push-discipline gate** — evaluate a mechanical check (pre-LIVE) that the registry
   working tree is clean and pushed before a controller reflash is performed.
5. **`map.json` field confirmation** with the HVAC controller firmware (external project)
   before its shape is frozen.

## Notes

Closes ADR-0007 open item 2 (schema/service/backup — service deliberately stays the
Phase-1 CLI) and ADR-0003 open item 1 (manifest format/location/tooling); leaves ADR-0003
item 3 (runtime push) open by design, now with a fixed data model to push. Aligns with
ADR-0008: the controller absorbs change, devices stay dumb, and every artifact a device
carries is reproducible from the repo. The git remote joins the controller and the
protocol header on the short list of things this architecture cannot afford to lose.
