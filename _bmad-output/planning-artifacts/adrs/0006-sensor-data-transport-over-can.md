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

**Proposed** — pending Alberto's acceptance. Additive to ADR-0001 (uses reserved category
space; no protocol break). The HVAC side (local HVAC control firmware) is **out of scope** —
this ADR covers only **how environmental sensor data is carried over the CAN bus** and
reaches the consumer.

## Context

Each room gets a **SEN66** (PM1/2.5/4/10, RH, T, VOC index, NOx index, CO2) and an
**SHT45** (precision T/RH). The sensors are I2C and have no processor; a **CAN node**
provides the I2C master and the CAN uplink. A **dedicated HVAC controller** (separate from
the lighting controller of ADR-0003; firmware already built by Alberto) consumes the data,
publishes it to Home Assistant, and drives HVAC.

This is the **revisit trigger named in ADR-0004 (D2)**: value-carrying message types now
proliferate. The resolution is the *light* typed-payload scheme D2 anticipated — the
measurement type rides the ID and *implies* the value's encoding — not a heavy DPT registry.

ADR-0001 explicitly reserved category space for "future message classes (sensors, …)", so
this slots in without a re-cut.

## Decision

### 1. New category `CAT_SENSOR` (low priority)

Add `CAT_SENSOR` using a reserved category value (e.g. `4`). Because CAN arbitrates by ID
(lower = higher priority) and category is the top field, a high category number makes
sensor traffic **yield** to INPUT (buttons), OUTPUT, and STATUS — correct, since readings
are periodic and non-urgent.

### 2. SENSOR frame ID layout (source-addressed, like INPUT/STATUS)

```
Bit: 28 27 26 │ 25 ........ 18 │ 17 ........ 10 │ 9 8 7 6 5 │ 4 3 2 1 0
     C  C  C  │ R (room:8)     │ B (board:8)    │ M M M M M │ x x x x x
C = CAT_SENSOR     M = measurement_type (5 bits, 32 values)     x = reserved (5)
```

The consumer decodes `room / board / measurement_type` straight from the `can_id` (a
category-mask subscription, same shape as the INPUT/STATUS handlers).

### 3. `measurement_type` enum (one frame per measurement)

Distinguishes the two T/RH sources: `SHT45_TEMP, SHT45_RH, SEN66_TEMP, SEN66_RH,
SEN66_PM1_0, SEN66_PM2_5, SEN66_PM4_0, SEN66_PM10, SEN66_VOC_INDEX, SEN66_NOX_INDEX,
SEN66_CO2` (11 → fits 5 bits with headroom).

### 4. Value encoding (the light typed-payload scheme)

Payload = `[PROTO_V1, val_lo, val_hi]` — a little-endian 16-bit value whose meaning is
implied by `measurement_type`:

| Quantity | Encoding |
|---|---|
| Temperature | `int16`, centi-°C (×100) → 2143 = 21.43 °C |
| Relative humidity | `uint16`, ×100 (0–10000 = 0–100 %) |
| PM1.0 / 2.5 / 4 / 10 | `uint16`, ×10 µg/m³ (0.1 resolution) |
| VOC index / NOx index | `uint16`, 1–500 (index, no scaling) |
| CO₂ | `uint16`, ppm (0–65535) |

One measurement per frame keeps the model uniform (subject in ID, value in payload). Load
is negligible: ~11 frames/room/cycle at a 10–30 s cadence is a few tens of frames/s even
for a whole house — trivial against 125 kbps and (per CAT_SENSOR's low priority) never
delays button traffic.

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
controller to ADR-0003's lighting controller — independent subsystems, so a fault in one
does not affect the other.

### 7. Heartbeats

Sensor nodes emit normal STATUS heartbeats like every other node, so the gateway/controller
can monitor their health.

## Consequences

### Positive
- Additive — reserved category space, no protocol break (ADR-0001).
- Uniform with the existing model (subject in ID, value in payload); same handler shape.
- Closes ADR-0004 D2 with the *light* typed-payload scheme (no heavy registry).
- Topology unaffected (ADR-0005): trivial load, carried by forward-all bridges, low priority.
- Dedicated HVAC controller isolates the HVAC subsystem from lighting.

### Negative / costs
- New firmware profile (I2C drivers): ESPHome has `sht4x`; **verify SEN66/SEN6x support** —
  newer part, may need a custom/external component (Sensirion ships a driver). The SEN66
  must free-run for its VOC/NOx gas-index algorithm.
- Combined nodes couple failures (a host node's death loses its buttons *and* its sensors).
- The host-shares-the-sensor's-room rule constrains which node a sensor may attach to.

### Open items
1. **Confirm `CAT_SENSOR` value** and freeze the `measurement_type` enum + encoding table in
   `canbus_protocol.h`.
2. **Verify ESPHome SEN66 support** (or write the custom I2C component).
3. **Verify SEN66 power** over QwiicBus per run.
4. **Sampling cadence** per measurement (e.g. fast for CO2/PM vs slow for T/RH).
5. Encoders/decoders + a category-mask handler on the HVAC controller.

## Notes
Depends on ADR-0001 (categories/IDs). Realises ADR-0004 D2 (light typed payloads). Consumer
is a dedicated controller in the spirit of ADR-0003. Commissioning of sensor nodes uses the
ADR-0002 selector, generalised there to a dedicated commissioning button for nodes without a
user button.
