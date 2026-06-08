---
adr: 0006
title: 'Sensor data transport over CAN (CAT_SENSOR)'
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
  - _bmad-output/planning-artifacts/adrs/0004-information-model-and-addressing-vs-knx.md
  - _bmad-output/planning-artifacts/adrs/0005-can-bus-topology-segmented-multi-bus.md
  - firmware/common/canbus_protocol.h
---

# ADR-0006: Sensor data transport over CAN (CAT_SENSOR)

## Status

**Proposed — re-keyed by ADR-0007 (2026-06-06).** Under the flat-`node_id` model (Extended IDs,
`[category:4][node_id:13][reserved:12]`), `CAT_SENSOR` is a first-class **4-bit category** and
sensor frames are `[CAT_SENSOR][node_id]` with `measurement_type` **and** the value **in the
payload** (the ID's low bits stay reserved); the room is derived centrally from `node_id`. The
measurement-type enum and value-encoding table below are unchanged — only the addressing moves
to `node_id`. The HVAC side remains **out of scope**.

## Context

Each room gets a **SEN66** (PM1/2.5/4/10, RH, T, VOC index, NOx index, CO2) and an
**SHT45** (precision T/RH). The sensors are I2C and have no processor; a **CAN node**
provides the I2C master and the CAN uplink. A **dedicated HVAC controller** (separate from
the lighting controller of ADR-0003; firmware already built by Alberto) consumes the data,
publishes it to Home Assistant, and drives HVAC.

This is the **revisit trigger named in ADR-0004 (D2)**: value-carrying message types now
proliferate. The resolution is the *light* typed-payload scheme D2 anticipated — the CAN ID
carries source identity and channel, while the payload carries a compact measurement type
that *implies* the value's encoding — not a heavy DPT registry.

ADR-0001 explicitly reserved category space for "future message classes (sensors, …)", so
this slots in without a re-cut.

## Decision

### 1. New category `CAT_SENSOR = 4` (low priority)

Add `CAT_SENSOR = 4`. Because CAN arbitrates by ID (lower = higher priority) and category
is the top field, this makes sensor traffic **yield** to INPUT (buttons), OUTPUT, and
STATUS — correct, since readings are periodic and non-urgent.

### 2. SENSOR frame ID layout (source-addressed, like INPUT/STATUS)

```
Bit: 28 27 26 │ 25 ........ 18 │ 17 ........ 10 │ 9 ................ 0
  C  C  C  │ R (room:8)     │ B (board:8)    │ K K K K K K K K K K
C = CAT_SENSOR     K = channel / sensor instance (10 bits)
```

The consumer decodes `room / board / channel` straight from the `can_id` (a category-mask
subscription, same shape as the INPUT/STATUS handlers) and decodes `measurement_type` from
the payload. `channel = 0` is the default and expected value for the initial deployment.
Non-zero channels are reserved for the rare case of multiple physical sensor packages or
instances on the same host node; using 10 bits here gives 1024 source instances without
constraining the measurement namespace.

### 3. `measurement_type` enum (one frame per measurement)

Freeze the initial `uint16_t measurement_type` values in `canbus_protocol.h`:

| Value | Name |
|---:|---|
| `0` | `SENSOR_MEAS_INVALID` / reserved |
| `1` | `SENSOR_SHT45_TEMP` |
| `2` | `SENSOR_SHT45_RH` |
| `3` | `SENSOR_SEN66_TEMP` |
| `4` | `SENSOR_SEN66_RH` |
| `5` | `SENSOR_SEN66_PM1_0` |
| `6` | `SENSOR_SEN66_PM2_5` |
| `7` | `SENSOR_SEN66_PM4_0` |
| `8` | `SENSOR_SEN66_PM10` |
| `9` | `SENSOR_SEN66_VOC_INDEX` |
| `10` | `SENSOR_SEN66_NOX_INDEX` |
| `11` | `SENSOR_SEN66_CO2` |

The enum distinguishes the two T/RH sources. Values `12`-`65535` remain reserved for future
measurement types or a later structured registry.

### 4. Value encoding (the light typed-payload scheme)

Payload = `[PROTO_V1, sensor_status, meas_lo, meas_hi, val0, val1, val2, val3]` — a status
byte, a little-endian `uint16_t measurement_type`, and a little-endian 32-bit value whose
meaning is implied by `measurement_type`:

| Status | Name | Semantics |
|---:|---|---|
| `0` | `SENSOR_STATUS_OK` | `val` is valid and should be published. |
| `1` | `SENSOR_STATUS_WARMING_UP` | Sensor is present but not ready; ignore `val`. |
| `2` | `SENSOR_STATUS_UNAVAILABLE` | Sensor/component did not produce a reading; ignore `val`. |
| `3` | `SENSOR_STATUS_ERROR` | Sensor reported an error; ignore `val`. |
| `4` | `SENSOR_STATUS_OUT_OF_RANGE` | Reading was outside representable/allowed range; ignore `val`. |

Consumers publish numeric values only when `sensor_status == SENSOR_STATUS_OK`; otherwise
the corresponding HA entity is marked unavailable/diagnostic as appropriate.

| Quantity | Encoding |
|---|---|
| Temperature | `int32`, centi-°C (×100) → 2143 = 21.43 °C |
| Relative humidity | `uint32`, ×100 (0–10000 = 0–100 %) |
| PM1.0 / 2.5 / 4 / 10 | `uint32`, ×10 µg/m³ (0.1 resolution) |
| VOC index / NOx index | `uint32`, 1–500 (index, no scaling) |
| CO₂ | `uint32`, ppm |

One measurement per frame keeps the model uniform: source/channel identity in the ID,
measurement type and value in the payload. The initial default cadence is **30 s for every
measurement**. The consumer marks a measurement stale/unavailable if it has not received a
fresh `SENSOR_STATUS_OK` frame for that `room/board/channel/measurement_type` within
**90 s**. Load is negligible: ~11 frames/room per 30 s is a few frames/s even for a whole
house — trivial against 125 kbps and (per CAT_SENSOR's low priority) never delays button
traffic.

### 5. Sensor-node profile — dedicated **or** combined, per room

The sensor node is the standard CAN node platform (CANBed RP2040 + I2C). The sensors sit
in a ventilated in-wall casing (built and field-validated by Alberto), reached over
**differential I2C extension (SparkFun QwiicBus)** for runs of a few metres. Per room:

- **Dedicated node** — node + sensors as a self-contained unit (carries the sensor's own room
  address). Use where no same-room button node is in range.
- **Combined** — sensors hung off a nearby **same-room** button node via QwiicBus; that node
  emits both `INPUT` and `CAT_SENSOR` frames.

A **mixed deployment is expected and fine** — the bus/protocol is identical for both.

**Binding rule (important):** a `CAT_SENSOR` frame carries the **host node's** `(room,
board)`, so a sensor inherits its host's room identity. **The host node must be addressed to
the sensor's physical room** — never hang a sensor off a node in a different room, or the
reading is mis-attributed.

**Power:** the SEN66 runs its fan + gas-sensing continuously (more than an idle node).
Verify its voltage/current over the QwiicBus run (small drop at a few metres, but confirm
against the host rail and fan inrush); power locally if marginal.

### 6. Consumer

The **dedicated HVAC controller** subscribes to `CAT_SENSOR` (category-mask filter),
decodes, publishes the readings to HA as sensor entities, and feeds HVAC. It is a parallel
controller to ADR-0003's lighting controller for operation, but **not** a commissioning
authority: node address assignment, re-homing, replacement, and the live
`(hwid → room/board/profile)` registry remain owned by the ADR-0003 controller + HA UI
defined in ADR-0002. The HVAC controller may read exported registry metadata for friendly
names and diagnostics, but it does not allocate addresses.

### 7. Heartbeats

Sensor nodes emit normal STATUS heartbeats like every other node, so the gateway/controller
can monitor their health.

## Consequences

### Positive
- Additive — uses `CAT_SENSOR = 4`, no protocol break (ADR-0001).
- Uniform with the existing model (source/channel in ID, typed value in payload); same
  category-mask handler shape.
- Closes ADR-0004 D2 with the *light* typed-payload scheme (no heavy registry).
- Topology unaffected (ADR-0005): trivial load, carried by forward-all bridges, low priority;
  the topology invariant is that `CAT_SENSOR` from every segment must reach the HVAC
  controller.
- Dedicated HVAC controller isolates the HVAC subsystem from lighting.

### Negative / costs
- New firmware profile (I2C drivers): ESPHome has `sht4x`; **verify SEN66/SEN6x support** —
  newer part, may need a custom/external component (Sensirion ships a driver). The SEN66
  must free-run for its VOC/NOx gas-index algorithm.
- Combined nodes couple failures (a host node's death loses its buttons *and* its sensors).
- The host-shares-the-sensor's-room rule constrains which node a sensor may attach to.

### Open items
1. **Implement protocol constants/helpers** in `canbus_protocol.h`: `CAT_SENSOR = 4`,
  measurement enum, status enum, `SENSOR_PAYLOAD_MIN = 8`, `can_sensor_id()`,
  `id_sensor_channel()`, `payload_sensor_measurement()`, `payload_sensor_value32()`, and
  value/status decoders.
2. **Verify ESPHome SEN66 support** (or write the custom I2C component).
3. **Verify SEN66 power** over QwiicBus per run.
4. Encoders/decoders + a category-mask handler on the HVAC controller, including the 90 s
  staleness rule.
5. Extend the registry/commissioning UI with node role and attached sensor metadata where
  needed, so the same-room host rule can be validated.

## Notes
Depends on ADR-0001 (categories/IDs). Realises ADR-0004 D2 (light typed payloads). Consumer
is a dedicated controller in the spirit of ADR-0003, but commissioning authority stays with
the ADR-0002 registry owner. Commissioning of sensor nodes uses the ADR-0002 selector,
generalised there to a dedicated commissioning button for nodes without a user button.
