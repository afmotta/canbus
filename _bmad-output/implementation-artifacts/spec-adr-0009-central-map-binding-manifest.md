---
title: 'Ratify ADR-0009 and un-stub the binding-manifest hash'
type: 'feature'
created: '2026-06-13'
baseline_commit: 'e3d1b099186997b96a108a1d25e36ef4eb40b2a1'
status: 'done'
context:
  - '{project-root}/_bmad-output/project-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/adrs/0009-central-map-binding-manifest-system-of-record.md'
  - '{project-root}/_bmad-output/planning-artifacts/adrs/0003-centralized-single-controller-with-onboard-fallback.md'
  - '{project-root}/_bmad-output/planning-artifacts/adrs/0007-flat-node-id-with-central-meaning-map.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** ADR-0009 makes the git repo the system of record for identity, placement, and bindings, but it is still `Proposed`, and the `ha_ready` arbitration that depends on it is stubbed: the gateway and HA both carry `manifest_hash: "dev-unbound"` (a hardcoded literal), so the hash term that is supposed to guard binding-version agreement guards nothing.

**Approach:** Ratify ADR-0009 with the repo's accepted-ADR convention, then land the minimal real slice that un-stubs the arbitration: a new `registry/bindings.yaml` manifest (§2), a stdlib canonical-hash function (§3), and generator wiring that stamps that hash into a compiled `bindings.h` constant the gateway compares — replacing `dev-unbound`. The broader export/visibility layer (map.json, full bindings table, generated HA package, drift entities) is deferred to a follow-up spec.

## Boundaries & Constraints

**Always:** Use the accepted-ADR frontmatter + `**Accepted (2026-06-13).**` Status convention (ADR-0003/0007/0008). Keep `generate_nodes.py` and `bindings.py` **stdlib-only** (no PyYAML). Keep `canonical_hash` pure and natively tested (`ha_arbitration.h` precedent): SHA-256 over the *parsed* bindings structure with sorted keys (not raw bytes), truncated to 16 hex chars. `bindings.h` is generated + committed + frozen-additive. Validate every binding's `node_id` against `nodes.csv` and reject unknown ids / duplicate `(node_id, button, event)` keys. The gateway and the HA heartbeat must end up carrying the *same* generated hash.

**Ask First:** If the constrained-subset YAML reader cannot express a binding shape you need (escalate reader-vs-PyYAML before adding a dependency); if un-stubbing forces a *breaking* change to `canbus_protocol.h`, the `node_map.h` struct, or the wire protocol; if the action vocabulary needs more than the minimal `relay: <channel>, op: on|off|toggle` form (ADR-0009 open item 1, blocked on ADR-0003 controller-board selection — ship minimal, grow additively).

**Never:** Do not bump `PROTO_V1` or change any CAN ID / payload layout (pipeline + docs only). Do not emit `map.json`, the full compiled `BINDINGS[]` table, a generated HA package, or drift-visibility entities — those are the deferred follow-up (logged in deferred-work). Do not build runtime binding push or wire bindings into the gateway fallback *action* (still log-only). Do not hand-edit generated `nodes/`, `node_map.h`, or `bindings.h`. Do not resolve ADR-0009 open items 1/3/4/5.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Hash determinism | `bindings.yaml` with same data, reordered keys/bindings + reformatted whitespace/comments | Identical 16-hex hash | N/A |
| Hash sensitivity | a binding's `op` changes `on`→`toggle` | hash changes | N/A |
| Empty manifest | `schema_version` + `bindings: []` | generator succeeds; stable hash over the empty manifest | N/A |
| Invalid binding | binding references a `node_id` absent from `nodes.csv`, or a duplicate `(node_id,button,event)` key | generator aborts, writes nothing | `sys.exit(1)`, message names the offending key |
</frozen-after-approval>

## Code Map

- `_bmad-output/planning-artifacts/adrs/0009-central-map-binding-manifest-system-of-record.md` -- target ADR to ratify (frontmatter + Status prose).
- `_bmad-output/planning-artifacts/adrs/0007-flat-node-id-with-central-meaning-map.md` -- open item 2 to mark Resolved-by-ADR-0009 (in-place ~~strike~~ + **Resolved**, per ADR-0003 item 4 exemplar).
- `_bmad-output/planning-artifacts/adrs/0003-centralized-single-controller-with-onboard-fallback.md` -- open item 1 to mark Resolved-by-ADR-0009.
- `firmware/registry/bindings.yaml` -- NEW manifest: `schema_version: 1` + `bindings` list keyed `(node_id, button, event)` → `relay`/`op` (§2).
- `firmware/registry/nodes.csv` -- existing registry; validation source for binding node_ids (unchanged).
- `firmware/tools/bindings.py` -- NEW stdlib module: constrained-subset loader, registry validation, `canonical_hash()` (§3).
- `firmware/tools/generate_nodes.py` -- extend `main()`: load+validate bindings, compute hash, emit `bindings.h`, print the hash in the run summary.
- `firmware/protocol/bindings.h` -- NEW generated: `BINDINGS_MANIFEST_HASH` constant, node_map.h-style header (the full `BINDINGS[]` table + a generated-at stamp are the deferred slice).
- `firmware/gateway/gateway.yaml` -- include `bindings.h`; drop the `manifest_hash: "dev-unbound"` substitution; compare `BINDINGS_MANIFEST_HASH` in `ha_readiness_heartbeat`.
- `firmware/gateway/ha_arbitration_automations.yaml` -- replace the live `dev-unbound` literal with the generator-printed hash; document the (interim) re-paste step.
- `firmware/tests/test_bindings.py` -- NEW native Python test for canonicalization + hash + validation.
- `firmware/README.md` -- document the bindings manifest, the canonical hash, the test command, and the interim HA hash re-paste.
- `_bmad-output/implementation-artifacts/deferred-work.md` -- already logged the deferred ADR-0009 slices + open items 1/3/4/5 (verify present; do not duplicate).

## Tasks & Acceptance

**Execution:**
- [x] `adrs/0009-...md` -- flip `status: 'Proposed'`→`'Accepted'`, add `acceptedDate: '2026-06-13'`, rewrite Status to `**Accepted (2026-06-13).**` preserving substance -- ratify the doctrine.
- [x] `adrs/0007-...md` + `adrs/0003-...md` -- mark ADR-0007 open item 2 and ADR-0003 open item 1 Resolved-by-ADR-0009 in place -- close the items ADR-0009 answers.
- [x] `firmware/tools/bindings.py` -- NEW: constrained-subset YAML reader for the fixed schema (scalars only, no nesting/anchors), registry validation (known node_id, unique key), `canonical_hash(parsed)` = SHA-256 over `json.dumps(sort_keys=True)` truncated to 16 hex -- the testable hash core.
- [x] `firmware/tests/test_bindings.py` -- NEW: assert hash determinism (key/order/whitespace-invariant), sensitivity (op change flips hash), empty-manifest stability, and validation rejects unknown node_id + duplicate key -- locks the I/O matrix.
- [x] `firmware/registry/bindings.yaml` -- NEW: `schema_version: 1` + a minimal `bindings` seed (or empty list) referencing only existing nodes 100/101 -- the manifest source of record.
- [x] `firmware/tools/generate_nodes.py` -- extend `main()`: import `bindings`, load+validate, compute hash, emit `bindings.h`, surface the hash in the summary -- one run stamps the gateway's hash source.
- [x] `firmware/gateway/gateway.yaml` -- include `bindings.h`, remove the `manifest_hash` substitution, compare `BINDINGS_MANIFEST_HASH` in the `ha_readiness_heartbeat` service lambda -- un-stub the arbitration.
- [x] `firmware/gateway/ha_arbitration_automations.yaml` + `firmware/README.md` -- set the heartbeat hash to the generated value, document the manifest/hash/test + interim re-paste -- HA echoes the real hash; guidance current.

**Acceptance Criteria:**
- Given ADR-0009 is the system-of-record decision, when its frontmatter/Status are reviewed, then it is `Accepted (2026-06-13)` and ADR-0007 item 2 / ADR-0003 item 1 read as resolved by it.
- Given `bindings.yaml` is the only hash input, when `generate_nodes.py` runs, then it prints a 16-hex hash and `bindings.h` defines `BINDINGS_MANIFEST_HASH` equal to it.
- Given the arbitration was stubbed, when the gateway compiles, then no `dev-unbound` literal remains in the gateway or live HA config and the gateway compares the generated `BINDINGS_MANIFEST_HASH`.
- Given this is pipeline-only, when `git diff -- firmware/protocol/canbus_protocol.h` is reviewed, then no protocol constant or payload layout changed and `PROTO_V1` is untouched.

## Design Notes

**Stdlib-only YAML (the load-bearing decision):** the generator must stay stdlib-only, but §2 mandates YAML. The `bindings.py` constrained-subset reader (scoped in its task) resolves this and is itself unit-testable; a binding shape the subset can't express is the Ask-First PyYAML escalation. Canonicalize from the *parsed* structure with `sort_keys=True` so formatting/comments never change identity.

**bindings.h shape (frozen-additive, mirrors node_map.h):** this slice emits only `inline constexpr char BINDINGS_MANIFEST_HASH[]`, kept deterministic (no generation timestamp) so regenerating unchanged bindings produces no diff. The compiled `struct BindingEntry {...}; BINDINGS[]` table and a generated-at stamp are the deferred follow-up (they belong with `map.json` / drift-visibility, §4/§6/§7), so the header is the manifest-hash carrier now and grows additively later.

## Verification

**Commands:**
- `python3 firmware/tests/test_bindings.py` -- expected: all assertions pass.
- `python3 firmware/tools/generate_nodes.py` -- expected: succeeds, prints the manifest hash, regenerates `nodes/`, `node_map.h`, and `bindings.h`.
- `grep -rn "dev-unbound" firmware/` -- expected: no live config matches (history/comments may mention it).
- `grep -n "BINDINGS_MANIFEST_HASH" firmware/protocol/bindings.h firmware/gateway/gateway.yaml` -- expected: defined in the header, compared in the gateway.
- `esphome compile firmware/gateway/gateway.yaml` -- expected: SUCCESS (includes `bindings.h`).
- `git diff -- firmware/protocol/canbus_protocol.h` -- expected: empty (no protocol change).

**Manual checks (if no CLI):**
- Confirm the hash in `bindings.h`, the value the gateway compares, and the value in the HA heartbeat automation are byte-for-byte identical.

## Suggested Review Order

**The hash contract (start here)**

- The canonical hash: sort + sorted-keys JSON so formatting/order never change identity.
  [`bindings.py:163`](../../firmware/tools/bindings.py#L163)

- The strict-subset YAML reader — why no PyYAML, and the parse rules it enforces.
  [`bindings.py:76`](../../firmware/tools/bindings.py#L76)

- Registry validation: unknown node_id, duplicate key, minimal op vocabulary.
  [`bindings.py:134`](../../firmware/tools/bindings.py#L134)

**Stamping the hash into one place, all consumers**

- Generator validates + hashes + emits `bindings.h`; aborts on a bad manifest.
  [`generate_nodes.py:142`](../../firmware/tools/generate_nodes.py#L142)

- The generated, deterministic hash constant the gateway compiles against.
  [`bindings.h:10`](../../firmware/protocol/bindings.h#L10)

**Un-stubbing the arbitration**

- Gateway now compares `BINDINGS_MANIFEST_HASH` — no more `dev-unbound` substitution.
  [`gateway.yaml:67`](../../firmware/gateway/gateway.yaml#L67)

- HA heartbeat echoes the real generated hash (interim hand-paste, documented).
  [`ha_arbitration_automations.yaml:40`](../../firmware/gateway/ha_arbitration_automations.yaml#L40)

**The decision + manifest source**

- ADR-0009 ratified; closes ADR-0007 item 2 / ADR-0003 item 1.
  [`0009...md:29`](../planning-artifacts/adrs/0009-central-map-binding-manifest-system-of-record.md#L29)

- The manifest itself: empty-but-valid seed, schema documented in comments.
  [`bindings.yaml:26`](../../firmware/registry/bindings.yaml#L26)

**Tests (last)**

- Determinism / sensitivity / validation — locks the I/O matrix.
  [`test_bindings.py:66`](../../firmware/tests/test_bindings.py#L66)
