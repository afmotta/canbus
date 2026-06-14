# Deferred Work (pending)

Open / blocked / decision-gated items only. **Resolved items, recorded decisions, and closed
follow-ups have moved to [completed-work.md](completed-work.md).** Each item tags its status:
_blocked_ (waits on a named decision), _external_, _bench/hardware_, _decision-gated_ (needs a
wire-spec call), or actionable now. Not bugs.

---

## Deferred from: spec-adr-0009-central-map-binding-manifest.md (2026-06-13)

ADR-0009 (central map & binding manifest — git as system of record) was accepted; its first implementation spec was **split** to stay within scope. The §4/§7 export pipeline, §6 drift-visibility entities, open items 3 (HA package) and 4 (push gate), and the two generator-review findings are all **resolved** (see [completed-work.md](completed-work.md)). What remains:

- **Binding action vocabulary beyond minimal (ADR-0009 open item 1)** [_blocked_ on ADR-0003 controller-board selection, open item 7] — `bindings.yaml` ships the minimal `relay: <channel>, op: on|off|toggle` action form and grows additively; richer actions (timers, scenes, Modbus addressing) wait on the controller board decision.
- **`map.json` field confirmation with HVAC firmware (ADR-0009 open item 5)** [_external_ project] — confirm the `map.json` shape against the HVAC controller firmware before freezing it; ties to the §7 export slice.

## Deferred from: ADR-0012 acceptance + implementation (2026-06-12)

ADR-0012 (hold/release press-phase gestures, **single vocabulary** — revised same day before commit from an initial per-button dual-mode form) was accepted and implemented in one pass: protocol header (`EVT_HOLD`/`EVT_HOLD_RELEASE` = 0x06/0x07; `EVT_LONG_PRESS`/`EVT_EXTRA_LONG_PRESS` and the dead pre-PRD alias block removed outright — pre-LIVE, nothing fielded; 0x04/0x05 left unassigned so old-firmware frames decode as "unknown" rather than misreading as hold), `packages/button.yaml` now emits click/double/triple + hold/hold_release on every button, HA reference automations (`firmware/gateway/ha_hold_automations.yaml`, incl. the derived long press), and the LIVE-checklist soak item. These open items are deferred to their owners.

- **`hold_ms` bench tuning (ADR-0012 open item 1)** [_bench_ / acceptance matrix] — the 800ms default in `packages/button.yaml` is a guess between "clearly not a click" (>0.5s + margin) and "doesn't feel laggy". It is also the derived long-press threshold (one fleet-wide knob serves both — a deliberate coupling). Tune on hardware, record the value in the acceptance matrix and the LIVE-freeze checklist's hold-soak line.
- **Hold-gesture bench acceptance matrix (ADR-0012 implementation plan §5)** [_bench_, 4-2/4-3 matrix pattern] — `hold` fires *while held* at ~hold_ms (not at release); `hold_release` fires on release of a hold and never after a bare click; single/double/triple unchanged; **no long/extra-long frames on the bus**; derived long press fires in HA on hold → release. Plus the §5 pull-test: kill the HA dim automation mid-hold and confirm the light lands at its bound.
- **Binding-manifest generation of hold bindings (ADR-0012 open item 2)** [_blocked_ on the ADR-0009 binding-action-vocabulary slice above] — when HA automations are generated from the manifest, hold/hold_release bindings (the §5 count-bound AND the derived long-press rule) must be generated, not hand-written; `ha_hold_automations.yaml` is the template. The same derivation rule must eventually exist in the gateway fallback path (ADR-0003) — one manifest source, two emitters.
- **Single-button direction-alternation UX (ADR-0012 open item 3)** [HA-side, reversible] — whether one button may alternate dim-up/dim-down per gesture (IKEA/Hue convention) or two-button up/down stays mandated. The shipped reference automations are two-button.

## Deferred from: spec-adr-0008-ratify-and-evolution-artifacts.md (2026-06-11)

ADR-0008 (post-LIVE firmware evolution) was accepted; these are its open items **not** addressed by the ratification spec, deferred to their owners.

- **USB-reachability mechanical spec (ADR-0008 open item 1)** [forthcoming physical/electrical topology ADR; ADR-0003 open item 8] — the concrete connector orientation / pigtail-vs-direct spec per mount type (wall box, bridge enclosure, sensor casing) that satisfies the §3 service-access rule. ADR-0008 establishes the *requirement*; the mechanical detail is owned by the physical/electrical ADR, not this one.
- **Firmware artifact archival (ADR-0008 open item 3)** [release process / repo] — decide where compiled per-release UF2/bin images live (repo? release tags?) and what metadata ties each image to registry (`nodes.csv`) state. Feeds the LIVE-freeze checklist (`docs/live-freeze-checklist.md`); a years-later reflash campaign depends on it.
- **Spare-stock policy (ADR-0008 open item 4)** [ops / commissioning] — how many pre-flashed spare boards sit on the shelf for the board-swap path, and at what `node_id` allocation discipline (ADR-0007 id space). Supports `docs/reflash-campaign-runbook.md` Path B.

## Deferred from: code review of spec-adr-0006-sensor-node-firmware.md (2026-06-11)

- **`commission.py` writes `nodes.csv` before regeneration — mid-loop generator failure leaves artifacts inconsistent** [`firmware/tools/commission.py` `apply_assignment`] [_actionable now_ — sibling of the resolved `generate_nodes.py` validate-before-persist fix] — the CSV is persisted (`write_rows`), then `generate_nodes.main()` runs; if generation `sys.exit(1)`s on any invalid row (duplicate `(room, board)`, bad `sensors` value, …) the registry is updated while `nodes/` is partially regenerated and `node_map.h` stays stale. Interactive mode catches the SystemExit and continues with only a one-line message. Pre-existing write-then-validate ordering, surfaced — not caused — by the ADR-0006 sensors-column review; fix it by validating before persisting (dry-run pass) or writing CSV+map atomically after success.

## Deferred from: code review of spec-adr-0004-approve-and-align-artifacts.md (2026-06-10)

- **project-context.md still encodes the superseded ADR-0001 wire model** [`_bmad-output/project-context.md:25,150`, `firmware/protocol/canbus_protocol.h`, ADR-0007] [_actionable now_ — verified still present 2026-06-14] — the project context still says CAN uses ADR-0001 location-as-address semantics and warns "Never reintroduce the flat `node_id` model," while the active protocol header and accepted ADR-0007 use flat `node_id` + payload-carried message detail (`can_id_node()`, `node_map.h`). Pre-existing repo-context drift surfaced by the ADR-0004 approval review, not caused by it. Needs a dedicated doc-alignment follow-up so future agents stop receiving contradictory global rules (this file is loaded as ground truth at agent activation).

## Deferred from: code review of spec-adr-0003-ha-ready-arbitration.md (2026-06-10)

- **ACK timeout cannot revoke an event already delivered to HA** [`firmware/gateway/gateway.yaml`, ADR-0003] [_design — ADR-level when bindings become real_] — when the fallback fires after `ack_timeout_ms`, HA may still process the original `esphome.canbus_button` event later and act on it: no timeout value bounds HA's processing latency, so the timeout mechanism alone cannot eliminate double actions. The prototype now *measures* the double-action window (`LATE ACK ... late=+` WARN), but eliminating it needs ADR-level treatment when bindings become real: idempotent/toggle-safe action semantics, event revocation, or HA-side staleness checks (drop events older than X). Inherent to ADR-0003's design, surfaced — not caused — by this story.
- **Native tests are manual-only** [`firmware/tests/`] [_actionable now_; echoes [[project_status_hygiene_mechanical_gate]]] — the C++ tests (`test_protocol.cpp`, `test_ha_arbitration.cpp`, `test_bridge_forwarding.cpp`) run only via the README `g++` one-liners, and the Python suites (`test_bindings.py`, `test_generate_exports.py`, `test_push_gate.py`) are likewise run by hand — nothing executes them automatically, so the pure-logic layer can regress silently. A tiny `make test` / pre-commit / CI step would close it. Pre-existing situation, now broader as the test suite has grown.
- **Root `.gitignore` still references pre-reorg paths** [`.gitignore`] [_actionable now_ — verified 2026-06-14] — the root file lists `firmware/secrets.yaml` / `firmware/.esphome/`, but post-reorg the real paths are `firmware/gateway/secrets.yaml` / `firmware/gateway/.esphome/` (currently protected only by the ESPHome-generated `firmware/gateway/.gitignore`). Update the root file to match the role-based layout. Pre-existing, surfaced by this review.

## Deferred from: code review of 3-1-gateway-base-configuration-twai-esp-idf-and-native-api.md (2026-06-02)

- **Service `send_data()` error handling** [`firmware/gateway.yaml`, ADR-0003] [_future command-reliability story_] — services log canbus errors but don't implement recovery, retry, or user notification. Pre-existing design pattern; not regression. **Reviewed 2026-06-03 — confirmed story-scoped, not a patch.** Services already `ESP_LOGW` on non-OK `send_data()`; genuine retry/backoff/timeout/HA-notification needs a design (retry count, command idempotency, timeout window) that belongs in a dedicated **command-reliability story**. Stuck-frame fault surfacing (from the 3-2 rate-limit review, now a recorded decision in [completed-work.md](completed-work.md)) folds into the same story as fault detection.

## Decision-gated (cannot fix without a protocol/wire-spec decision)

- **`button_index` is still not range-checked inside `button_payload`** [`firmware/protocol/canbus_protocol.h`] — the **0–7** invariant (the standard 8-button set, `btn0`–`btn7` in `packages/base_node.yaml`) is enforced at the generator/config layer; nodes only ever use those declared indices. A runtime clamp has no defined target: there is **no wire-spec-defined invalid-button encoding**. Reviewed 2026-06-03, refreshed 2026-06-14 (the set grew 6→8 buttons and the header moved to `protocol/`) — leaving deferred rather than fabricating protocol semantics; needs a wire-spec decision before any guard is added.
- **`node_id ≥ 8192` would silently produce colliding CAN IDs** [`firmware/protocol/canbus_protocol.h`] — `can_id()` masks `node_id & NODE_FIELD_MASK` (`0x1FFF`, the 13-bit node field, max 8191); a larger id cannot be represented. `can_id()` returns `uint32_t` inside hot `!lambda`s with no error channel, so there is nowhere to surface a guard at runtime. The real ceiling already lives in `generate_nodes.py` (`NODE_ID_MAX = 8191`, validated). Reviewed 2026-06-03, refreshed 2026-06-14 (the field widened from 9-bit/511 to 13-bit/8191 with the ADR-0007 flat-node_id redesign) — appropriately enforced at the generator, not the header.
