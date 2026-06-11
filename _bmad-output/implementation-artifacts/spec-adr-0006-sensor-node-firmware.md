---
title: 'Accept ADR-0006 + node-side CAT_SENSOR sensor firmware'
type: 'feature'
created: '2026-06-11'
status: 'done'
baseline_commit: '1a56f4927b7cc850fe2088f2a6af19d0132d06be'
context:
  - '_bmad-output/planning-artifacts/adrs/0006-sensor-data-transport-over-can.md'
  - '_bmad-output/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** ADR-0006 (sensor data transport over CAN, `CAT_SENSOR`) is still `Proposed` even though its protocol layer (enums, `sensor_payload()`, decoders) was merged in PR #19, and no node firmware exists to actually read the SHT45/SEN66 and emit `CAT_SENSOR` frames.

**Approach:** Flip ADR-0006 to `Accepted` (reconciling its Status/Open-items text with what is already merged), and implement the node-side TX path: a `sensor_kit` ESPHome package (I2C + `sht4x` + `sen6x`) that emits one `CAT_SENSOR` frame per measurement every 30 s using the existing protocol helpers, wired into node generation via an optional `sensors` registry column.

## Boundaries & Constraints

**Always:**
- Use `canbus_protocol.h` helpers (`can_id(CAT_SENSOR, ${node_id})`, `sensor_payload(...)`, named constants) — never inline magic numbers in YAML lambdas.
- One measurement per frame; identity in the CAN ID, measurement type + value in the payload (flat node_id model, ADR-0007).
- Generated node files stay minimal; all sensor config lives in `firmware/packages/sensor_kit.yaml`; nodes opt in only via the registry → generator.
- I2C pins are substitution variables with defaults; mark them as UNVERIFIED against the CANBed schematic in comments and README.

**Ask First:**
- Any change to `canbus_protocol.h` (the protocol layer for ADR-0006 is already merged and frozen).
- Setting `sensors=1` on a real registry row (node100/node101) — deployment intent is Alberto's.
- Adding external components or pinning ESPHome version.

**Never:**
- Touch the gateway: the CAT_SENSOR consumer is the dedicated HVAC controller (external firmware, out of repo).
- Hand-edit files in `firmware/nodes/` (generated output).
- Implement ADR-0006 open item 5 (registry role metadata / same-room host validation) — explicitly deferred.
- Bump the protocol version (pre-live policy).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid reading | SEN66 CO2 = 612.4 ppm | Frame id `can_id(CAT_SENSOR, node_id)`, payload `[PROTO_V1, SENSOR_STATUS_OK, 11, 0, 612 LE32]` | N/A |
| Scaled reading | SHT45 T = 21.43 °C | value `2143` (int32 centi-°C, ×100 per ADR table) | N/A |
| Sensor not ready | `on_value` receives NaN (SEN66 warm-up / gas-index not stabilized) | Frame sent with `SENSOR_STATUS_UNAVAILABLE`, value 0 | Consumer ignores value per ADR §4 |
| Out of range | Negative value for an unsigned quantity (RH/PM/index/CO2) | Frame sent with `SENSOR_STATUS_OUT_OF_RANGE`, value 0 | Consumer ignores value |
| CAN TX failure | `send_data` returns != `ERROR_OK` | WARN log, frame dropped (same pattern as button.yaml) | No retry |
| Node without sensors | `sensors` column blank/0/missing | Generated yaml byte-identical to today's output | Generator accepts missing column |

</frozen-after-approval>

## Code Map

- `firmware/protocol/canbus_protocol.h` -- protocol layer already complete (CAT_SENSOR, enums, `sensor_payload()`, decoders). READ-ONLY here.
- `firmware/packages/base_node.yaml` / `button.yaml` -- pattern references: heartbeat interval + `can0` send, shared send script with TX-failure WARN.
- `firmware/tools/generate_nodes.py` -- TEMPLATE + CSV parsing; gains the optional `sensors` column.
- `firmware/tests/test_protocol.cpp` -- already covers sensor payload round-trip; no change expected.

## Tasks & Acceptance

**Execution:**
- [x] `firmware/packages/sensor_kit.yaml` -- new package: `i2c:` bus (substitutions `i2c_sda`/`i2c_scl`, defaults GPIO0/GPIO1, marked UNVERIFIED), `sht4x` (0x44) + `sen6x` (0x6B) at `update_interval: 30s`, one shared `script` `sensor_send(meas: uint16, value: int32, status: uint8)` that logs and sends via `can0`, per-measurement `on_value` lambdas mapping float → (scaled int32, status) per ADR §4 -- the core deliverable. *(Implemented with `sensor_send(meas, raw, scale, is_signed)` — the float→(value, status) mapping lives once in the script instead of 11 per-sensor lambdas.)*
- [x] `firmware/tools/generate_nodes.py` -- parse optional `sensors` column (blank/0 = off, back-compat with missing column); when truthy, add `sensor_kit: !include ../packages/sensor_kit.yaml` to the generated `packages:` block + header comment -- wires the package into the sanctioned provisioning flow.
- [x] `firmware/registry/nodes.csv` -- add `sensors` column, `0` for node100/node101. *(Also synced the two other CSV writers: `commission.py` would have silently dropped the column on every save; `allocate_node.py` now seeds `sensors=0`.)*
- [x] `firmware/tests/compile_sensor_node.yaml` -- hand-maintained compile-check config (`node_id: "999"`, includes base_node + sensor_kit) -- validates the build without touching generated `nodes/`.
- [x] `_bmad-output/planning-artifacts/adrs/0006-sensor-data-transport-over-can.md` -- frontmatter `Accepted`, rewrite Status section (accepted 2026-06-11; protocol layer merged PR #19; node TX path this change; consumer external), mark open items 1–2 resolved (`sen6x` is an official ESPHome component), keep 3–5 open/deferred.
- [x] `firmware/README.md` -- "Sensor kit (ADR-0006)" section: components, cadence, status mapping, UNVERIFIED I2C pin warning (verify against pinned CANBed schematic before flashing), `sensors` column usage.

**Acceptance Criteria:**
- Given a registry row with `sensors=1`, when `generate_nodes.py` runs, then the generated node yaml contains the `sensor_kit` include and `node_map.h` is unchanged in shape.
- Given the existing rows (sensors=0), when the generator runs, then `node100.yaml`/`node101.yaml` are unchanged except (at most) the documented header comment.
- Given `compile_sensor_node.yaml`, when `esphome config` (and `compile` if available) runs, then validation succeeds on ESPHome 2026.5.x with no external components.
- Given the ADR file, when read, then `status: 'Accepted'` and the Status section reflects the merged protocol layer.

## Spec Change Log

- 2026-06-11 (post-review, human renegotiation): Alberto verified the I2C wiring — SDA=GPIO6,
  SCL=GPIO7 (I2C1). The "mark pins UNVERIFIED" constraint in the frozen Always block is
  satisfied-then-superseded: defaults updated to GPIO6/GPIO7 and the UNVERIFIED warnings
  replaced with verified provenance in `sensor_kit.yaml`, README, and ADR open item 3.
  SEN66 QwiicBus power (open item 3) remains the only outstanding hardware check.

## Design Notes

- Status mapping is deliberately minimal: NaN → `SENSOR_STATUS_UNAVAILABLE` (covers SEN66 warm-up too — the node cannot reliably distinguish warm-up, and the consumer treats both identically per ADR §4); negative-for-unsigned → `SENSOR_STATUS_OUT_OF_RANGE`. `SENSOR_STATUS_WARMING_UP`/`ERROR` stay reserved for a later slice.
- Frames are sent even when status != OK so the consumer's 90 s staleness rule distinguishes "sensor degraded" from "node dead".
- Scaling lives in the shared `sensor_send` script (each `on_value` passes meas/raw/scale/signedness). The script runs `mode: queued` with 25 ms inter-frame spacing — a SEN66 update bursts 9 channels against the MCP2515's 3 TX mailboxes, so unspaced sends would systematically drop the later measurements (review finding). ±inf / int32-overflow raw values map to `OUT_OF_RANGE`.
- ESPHome ≥ 2025.x ships `sen6x` natively (PR esphome#9254 extended sen5x family); SEN66 over QwiicBus is plain I2C at the node end.

## Verification

**Commands:**
- `python3 firmware/tools/generate_nodes.py` -- expected: regenerates cleanly; node100/101 unchanged; CAN ID map prints.
- `g++ -std=c++17 -Wall -Wextra firmware/tests/test_protocol.cpp -o /tmp/proto && /tmp/proto` -- expected: exit 0.
- `esphome config firmware/tests/compile_sensor_node.yaml` -- expected: "Configuration is valid".
- `esphome compile firmware/tests/compile_sensor_node.yaml` -- expected: build succeeds (run if esphome + toolchain available; otherwise report skipped).

**Manual checks (if no CLI):**
- ADR-0006 frontmatter + Status section read as Accepted with accurate provenance.

## Suggested Review Order

**The acceptance (what was decided)**

- ADR flipped to Accepted: protocol layer was PR #19, this change ships the node TX path.
  [`0006-sensor-data-transport-over-can.md:24`](../planning-artifacts/adrs/0006-sensor-data-transport-over-can.md#L24)

- Open items 1–2 struck through with provenance; 3–5 stay open (power, HVAC consumer, role metadata).
  [`0006-sensor-data-transport-over-can.md:188`](../planning-artifacts/adrs/0006-sensor-data-transport-over-can.md#L188)

**Sensor TX path (the core firmware)**

- One queued send script owns the entire float→(value, status)→frame mapping; 11 call sites stay one-liners.
  [`sensor_kit.yaml:45`](../../firmware/packages/sensor_kit.yaml#L45)

- `mode: queued` + 25 ms delay paces bursts — 9 SEN66 channels vs 3 MCP2515 mailboxes (review finding).
  [`sensor_kit.yaml:46`](../../firmware/packages/sensor_kit.yaml#L46)

- NaN/inf/overflow/negative-unsigned guards before `lroundf` — UB-safe on 32-bit `long` (review finding).
  [`sensor_kit.yaml:60`](../../firmware/packages/sensor_kit.yaml#L60)

- I2C pin defaults flagged UNVERIFIED against the CANBed schematic; fleet-wide override point is here.
  [`sensor_kit.yaml:25`](../../firmware/packages/sensor_kit.yaml#L25)

- `sht4x` + `sen6x` (official component, resolves ADR open item 2) at the 30 s ADR cadence.
  [`sensor_kit.yaml:83`](../../firmware/packages/sensor_kit.yaml#L83)

**Registry wiring (how nodes opt in)**

- Strict `sensors` value parsing — blank/0/1 only, so a typo can't silently drop a kit.
  [`generate_nodes.py:155`](../../firmware/tools/generate_nodes.py#L155)

- Header-typo guard: a misspelled column would otherwise disable every kit with exit 0 (review finding).
  [`generate_nodes.py:148`](../../firmware/tools/generate_nodes.py#L148)

- Template emits the include + binding-rule comment only for sensors=1; sensors=0 output is byte-identical.
  [`generate_nodes.py:58`](../../firmware/tools/generate_nodes.py#L58)

- `commission.py` rewrites the CSV — without this it would silently drop the sensors column on every save.
  [`commission.py:26`](../../firmware/tools/commission.py#L26)

- `allocate_node.py` migrates legacy 5-column CSVs before appending 6-field rows (review finding).
  [`allocate_node.py:45`](../../firmware/tools/allocate_node.py#L45)

**Peripherals**

- Compile-check config — the sanctioned way to build base+kit without touching generated `nodes/`.
  [`compile_sensor_node.yaml:1`](../../firmware/tests/compile_sensor_node.yaml#L1)

- Registry gains the column; both real nodes stay sensor-less (deployment is Alberto's call).
  [`nodes.csv:1`](../../firmware/registry/nodes.csv#L1)

- Onboarding doc: status mapping, frame pacing, the honest sht4x-publishes-nothing caveat, pin warning.
  [`README.md:104`](../../firmware/README.md#L104)
