---
status: final
created: 2026-05-29
updated: 2026-05-29
---

# CAN Bus Smart Home — Proof of Concept PRD

## Overview

A bench-top proof of concept validating that a CAN bus button-control system built on ESPHome can reliably transmit button events from RP2040 nodes to a central gateway, and that Home Assistant can receive and correctly decode those events (button index, event type, room, board).

**Why this PoC matters:** The fienile (barn conversion) spans 3 floors and 19 rooms. Button nodes will be walled in permanently with no physical access after installation, and the RP2040 lacks WiFi so there is no OTA path. Every firmware choice bakes in for the life of the installation. The entire design therefore depends on "dumb nodes, smart gateway": node firmware is frozen, all logic lives in Home Assistant automations. Before committing to 100+ boards, this PoC validates the stack is sound on real hardware.

**Baseline:** As of PoC start, no node or gateway firmware has been compiled or run. The YAML and C++ are designed but unvalidated. The `on_frame` + `can_id_mask` + `homeassistant.event` chain is the highest-risk path and the first thing to prove out.

This PoC covers 2 button nodes and 1 gateway on a bench setup.

## Goals

1. Confirm the ESPHome CAN bus stack (MCP2515 on RP2040 nodes, native TWAI on ESP32-S3 gateway) compiles and runs correctly on the actual hardware.
2. Confirm button events (click, double-click, triple-click, long press, extra-long press) are detected on nodes and transmitted over CAN at 125 kbps.
3. Confirm the gateway receives frames from both nodes and forwards them to Home Assistant as `esphome.canbus_button` events with correct `room`, `board`, `button`, and `event` fields.
4. Confirm heartbeat frames are received and forwarded as `esphome.canbus_heartbeat` events.
5. Identify any ESPHome component or protocol issues before committing to large-scale hardware procurement.

## Non-Goals (PoC scope)

- CAT_OUTPUT (gateway → node commands): not implemented in this phase.
- Node health dashboard or alerting: heartbeat events reaching HA is sufficient.
- Per-floor gateways or multi-gateway topology.
- Physical installation in walls.
- OTA update capability on nodes.
- Production-quality HA automations; manual event inspection in HA Developer Tools is acceptable for validation.

## Hardware Bill of Materials

| Role                | Board                                      | Qty                 |
| ------------------- | ------------------------------------------ | ------------------- |
| Button node         | Seeed Studio CANBed RP2040 (SKU 102991596) | 2                   |
| Gateway             | Waveshare ESP32-S3-RS485-CAN               | 1                   |
| CAN bus termination | 120 Ω resistors (or board jumpers)         | 2 (one per bus end) |
| Power               | 9–28 V DC supply                           | 1 (for nodes)       |

> **Note:** CANBed RP2040 boards ship as kits requiring soldering of through-hole components (terminal blocks, DB9, pin headers, termination switch) before first use. This is a prerequisite for bench assembly.

### Node — CANBed RP2040

- MCU: RP2040
- CAN controller: MCP2515 (SPI0)
- CAN transceiver: MCP2551
- Power input: 9–28 V via CAN connector (regulated onboard to 3.3 V / 1 A)
- Flashing: USB (Micro-USB) only; no OTA
- Buttons: up to 6 per board (GPIO pins TBD — see OQ-1)

**Fixed SPI pin mapping:**

| Signal   | GPIO                                                                          |
| -------- | ----------------------------------------------------------------------------- |
| SPI CS   | GPIO9                                                                         |
| SPI SCK  | GPIO18                                                                        |
| SPI MOSI | GPIO19                                                                        |
| SPI MISO | GPIO16                                                                        |
| INT      | GPIO20 [ASSUMPTION: unverified — confirm from board schematic before compile] |

### Gateway — Waveshare ESP32-S3-RS485-CAN

- MCU: ESP32-S3-WROOM-1 (dual-core LX7, 16 MB flash, 8 MB PSRAM)
- CAN controller: ESP32-S3 native TWAI
- CAN transceiver: SN65HVD230 (3.3 V, isolated, 120 Ω jumper-selectable termination)
- Connectivity: WiFi 802.11 b/g/n (no Ethernet on this board)
- Power input: 7–36 V DC or USB-C 5 V
- RS485 interface: present but not used in this PoC

> **Note:** This board differs from the ESP32-S3-POE-ETH-8DI-8DO referenced in prior design notes. Key differences: no Ethernet (WiFi only), no PCA9554 I/O expander, no discrete digital inputs/outputs, no buzzer, no RGB LED. The gateway will reach Home Assistant over WiFi. The POE board remains the target for the full production deployment.

**CAN GPIO mapping:**

| Signal           | GPIO   |
| ---------------- | ------ |
| CAN TX (TWAI TX) | GPIO15 |
| CAN RX (TWAI RX) | GPIO16 |

## System Architecture

```text
[CANBed RP2040 node 0]──┐
                         ├──[CAN bus, 125 kbps]──[Waveshare ESP32-S3-RS485-CAN]──[WiFi]──[Home Assistant]
[CANBed RP2040 node 1]──┘
```

- Nodes detect button events locally via ESPHome `on_multi_click` and transmit CAN frames (CAT_INPUT category).
- Nodes emit heartbeat frames every 30 seconds (CAT_STATUS category).
- Gateway receives all frames via mask-based filtering, decodes them, and fires HA events via ESPHome native API over WiFi.
- Home Assistant receives events; validation is done via HA Developer Tools → Events.

## CAN Protocol v1 (PoC subset)

### CAN ID format (11-bit standard)

```text
Bits 10–9: Category (2 bits)
Bits 8–0:  Node ID (9 bits, 0–511)
```

Categories used in PoC:

| Category   | Value | Direction      | Purpose       |
| ---------- | ----- | -------------- | ------------- |
| CAT_INPUT  | 1     | Node → Gateway | Button events |
| CAT_STATUS | 3     | Node → Gateway | Heartbeat     |

### Design rationale: room and board in payload

ESPHome's `on_frame` trigger does not cleanly expose the received CAN ID as a variable inside the lambda. When the gateway uses mask-based filtering to match all button events at once (regardless of which node sent them), it cannot reliably decode the source node from the CAN ID alone. Room and board IDs are therefore embedded in the payload, making each frame self-describing. This is not over-engineering — it is a direct consequence of an ESPHome constraint.

> **Wire-spec amendment (2026-06-03, correct-course):** both node→gateway frames share a uniform
> `[version][type][room][board]` prefix, then message-specific content trailing toward the reserved
> tail. This unifies the `room`/`board` decoders across button and heartbeat and keeps the free bytes
> contiguous with the content for future growth. Heartbeat `uptime` is widened to a little-endian
> `uint16` (bytes 5-6). The byte-3 "button states bitmask" is **removed** — buttons are momentary
> and have no resting state. `PROTO_V1` is unchanged per the versioning policy below.
>
> **Versioning policy:** until the project is declared LIVE, `PROTO_V1` stays `0x01` and breaking
> payload changes are absorbed in place (all nodes reflashed in lock-step with the gateway — no
> fielded firmware to remain compatible with). **Declaring the project live is Alberto's explicit
> call.** Only after going live does a breaking payload change require a version bump.

### Button event frame (CAT_INPUT)

| Byte | Field            | Value                                                                                    |
| ---- | ---------------- | ---------------------------------------------------------------------------------------- |
| 0    | Protocol version | 0x01                                                                                     |
| 1    | Message type     | 0x01 (MSG_BUTTON_EVENT)                                                                  |
| 2    | Room ID          | 0–255                                                                                    |
| 3    | Board ID         | 0–255                                                                                    |
| 4    | Button index     | 0–5                                                                                      |
| 5    | Event type       | 0x01=click, 0x02=double_click, 0x03=triple_click, 0x04=long_press, 0x05=extra_long_press |
| 6–7  | Reserved         | 0x00                                                                                     |

### Heartbeat frame (CAT_STATUS)

| Byte | Field            | Value                                                  |
| ---- | ---------------- | ------------------------------------------------------ |
| 0    | Protocol version | 0x01                                                   |
| 1    | Message type     | 0x01 (MSG_HEARTBEAT)                                   |
| 2    | Room ID          | 0–255                                                  |
| 3    | Board ID         | 0–255                                                  |
| 4    | Error flags      | 0x00=healthy, 0x01=CAN TX fail, 0x02=bus-off           |
| 5–6  | Uptime (hours)   | uint16 little-endian, saturates at 65535 (~7.5 yr)     |
| 7    | Reserved         | 0x00                                                   |

## Functional Requirements

### FR-1: Node firmware — Button event detection

**FR-1.1** Each node firmware SHALL detect the following 5 event types per button using ESPHome `on_multi_click`:
- single click
- double click
- triple click
- long press (1–3 seconds)
- extra-long press (3+ seconds)

**FR-1.2** Multi-click patterns SHALL be ordered longest-first (triple → double → single → long → extra-long) to prevent shorter patterns from shadowing longer ones.

**FR-1.3** Click timing thresholds are compile-time constants; runtime adjustment is out of scope.

**FR-1.4** Each node SHALL support up to 8 buttons per board. Nodes standardize on the 8-button set (`btn0`–`btn7`) defined in `common/base_node.yaml`.

### FR-2: Node firmware — CAN transmission

**FR-2.1** On each button event, the node SHALL transmit a CAN frame with:
- CAN ID = `(CAT_INPUT << 9) | node_id`
- 8-byte payload as specified in the Button event frame table above

**FR-2.2** The node SHALL validate `x.size() >= 8` in all CAN frame receive lambdas before indexing any byte.

**FR-2.3** The CAN bus speed SHALL be 125 kbps. This rate was chosen as a conservative baseline appropriate for a low-frequency event bus (button presses + 30-second heartbeats across up to 100+ nodes); it is well within MCP2515 and TWAI capabilities and provides headroom for future message types.

**FR-2.4** The node SHALL use the MCP2515 CAN controller via SPI0 with a 16 MHz clock [ASSUMPTION: CANBed RP2040 ships with 16 MHz oscillator — confirm from board documentation before compile].

### FR-3: Node firmware — Heartbeat

**FR-3.1** Each node SHALL transmit a heartbeat frame every 30 seconds with:
- CAN ID = `(CAT_STATUS << 9) | node_id`
- 8-byte payload as specified in the Heartbeat frame table above

**FR-3.2** Error flags (payload byte 4) SHALL be set as follows: bit 0 (0x01) set when MCP2515 reports a TX error or TX timeout; bit 1 (0x02) set when MCP2515 reports bus-off state. Both are readable from MCP2515 error registers via the ESPHome MCP2515 component error callback or by polling the error flag global. Byte 4 = 0x00 when no errors are present.

### FR-4: Node firmware — Protocol header

**FR-4.1** All CAN frame construction and decoding SHALL use `canbus_protocol.h` for constants and helper functions. Raw bit shifts and magic numbers SHALL NOT appear in YAML lambdas.

**FR-4.2** `canbus_protocol.h` SHALL be included by both node and gateway firmware.

### FR-5: Gateway firmware — CAN reception

**FR-5.1** The gateway SHALL receive all CAT_INPUT frames using mask-based filtering:
- `can_id: 0x200`, `can_id_mask: 0x600` (matches all node IDs within the category regardless of source node)

**FR-5.2** The gateway SHALL receive all CAT_STATUS frames using mask-based filtering:
- `can_id: 0x600`, `can_id_mask: 0x600`

**FR-5.3** The gateway CAN interface SHALL use the native TWAI controller on GPIO15 (TX) and GPIO16 (RX) at 125 kbps.

### FR-6: Gateway firmware — Home Assistant event forwarding

**FR-6.1** On receiving a valid CAT_INPUT frame, the gateway SHALL fire a `esphome.canbus_button` event to Home Assistant with the following string fields:
- `room`: room ID extracted from payload byte 2
- `board`: board ID extracted from payload byte 3
- `button`: button index from payload byte 4
- `event`: event type string (`click`, `double_click`, `triple_click`, `long_press`, `extra_long_press`)

**FR-6.2** On receiving a valid CAT_STATUS frame, the gateway SHALL fire a `esphome.canbus_heartbeat` event with:
- `room`: room ID from payload byte 2
- `board`: board ID from payload byte 3
- `uptime`: uptime hours from payload bytes 5-6 (uint16 LE, as string)
- `errors`: error flags from payload byte 4 (as string)

**FR-6.3** All event data field values SHALL be strings. Integer values SHALL be converted via `to_string()` or `std::string()` before use in `homeassistant.event` data blocks.

**FR-6.4** Each `homeassistant.event` data field SHALL be populated by a per-field `!lambda` that re-decodes directly from the received frame vector `x`. The narrow constraint is that a variable declared in a *separate preceding* `lambda:` action is not in scope inside the data block (it runs in its own action context) — but a `!lambda` attached to the data field itself runs in `on_frame` scope and can read `x`. Globals staging is NOT required and is not used (corrected 2026-06-03; aligns with the implemented gateway).

### FR-7: Gateway firmware — Connectivity

**FR-7.1** The gateway SHALL connect to Home Assistant via ESPHome native API over WiFi [ASSUMPTION: WiFi credentials and HA API key will be provided at firmware build time].

**FR-7.2** [ASSUMPTION: Home Assistant instance is on the same WiFi network and reachable from the gateway].

### FR-8: Code generation — Node configuration

**FR-8.1** Node YAML files SHALL be generated by `generate_nodes.py` from `nodes.csv`. Hand-editing files in `nodes/` is prohibited.

**FR-8.2** `nodes.csv` SHALL define at minimum: `node_id`, `floor`, `room`, `board`, `location`, `gpio_list` for each node.

**FR-8.3** For the PoC, `nodes.csv` SHALL contain exactly 2 node entries with distinct `node_id` values, distinct `room` values, and assigned button GPIO lists.

**FR-8.4** `generate_nodes.py` SHALL print a CAN ID map on completion. The map SHALL be reviewed for duplicate IDs before flashing.

### FR-9: Validation acceptance criteria

**FR-9.1** For each of the 5 event types, pressing the corresponding button sequence on node 0 SHALL result in an `esphome.canbus_button` event appearing in HA Developer Tools → Events with correct `room`, `board`, `button`, and `event` values.

**FR-9.2** The same validation SHALL pass for node 1 (different `room` value).

**FR-9.3** Within 60 seconds of power-on, each node SHALL emit at least one heartbeat visible as `esphome.canbus_heartbeat` in HA. [ASSUMPTION: first heartbeat fires at power-on or within the first 30-second interval — actual timing is OQ-6, adjust window if needed after observation.]

**FR-9.4** Events from node 0 and node 1 SHALL be distinguishable by `room` and `board` field values.

**FR-9.5** All 10 event-type combinations (5 types × 2 nodes) SHALL produce a correctly decoded HA event with no missing or blank fields. The PoC passes only when all 10 are verified.

**FR-9.6** ESPHome logs on the gateway SHALL show zero CAN error frames during the validation run. Any error frame is a blocking defect requiring investigation before the PoC is declared successful.

## Non-Functional Requirements

**NFR-1 Compile-first:** Both node and gateway firmware SHALL compile successfully with `esphome compile` before any hardware is connected. A failed compile is a blocking defect.

**NFR-2 Lambda safety:** Every CAN frame receive lambda SHALL guard against short frames with `x.size() >= N` before indexing. Absence of this guard is a blocking defect.

**NFR-3 Protocol as single source of truth:** `canbus_protocol.h` is the sole location for protocol constants. Any constant duplicated in YAML is a defect.

**NFR-4 Framework:** Gateway SHALL use `esp-idf` framework (required for native TWAI). Arduino framework is incompatible with `esp32_can` on ESP32-S3 and SHALL NOT be used on the gateway.

**NFR-5 Node isolation:** Nodes SHALL have no WiFi, no ESPHome API, no OTA, no web server, no network logger. Node firmware is intentionally minimal — this is a feature, not a limitation, given the permanent installation constraint.

**NFR-6 CAN bus speed:** All devices on the bus SHALL use 125 kbps. Mismatched speeds cause bus errors and are not recoverable without power cycling.

**NFR-7 Termination:** The bus SHALL have exactly two 120 Ω termination resistors, one at each physical end. The PoC bench setup SHALL verify termination is in place before powering nodes.

## Open Questions

| #    | Question                                                                                                                                                                                 | Blocking?                                | Owner                  |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- | ---------------------- |
| OQ-1 | What are the exact GPIO numbers for user-facing button pins on the CANBed RP2040? The Longan Labs pinout diagram must be consulted before building `nodes.csv`.                          | Yes — blocks FR-1, FR-8                  | Alberto                |
| OQ-2 | Is the MCP2515 INT pin on the CANBed RP2040 actually GPIO20? Confirm from board schematic before first compile.                                                                          | Yes — blocks FR-2                        | Alberto                |
| OQ-3 | Does the CANBed RP2040 ship with a 16 MHz oscillator? The MCP_CAN library and ESPHome MCP2515 component default to this.                                                                 | Yes — blocks FR-2                        | Alberto                |
| OQ-4 | Does the ESPHome `on_frame` + `can_id_mask` + `homeassistant.event` chain on the gateway compile and behave as designed? This is the highest-risk software path and has not been tested. | Yes — blocks FR-5, FR-6                  | Alberto (compile test) |
| OQ-5 | How many buttons will actually be wired on each PoC node? Determines GPIO list in `nodes.csv`.                                                                                           | No — does not block compile; blocks FR-9 | Alberto                |
| OQ-6 | Will the first heartbeat fire at node power-on (t=0), or only after the first 30-second interval?                                                                                        | No — affects FR-9.3 test window only     | Observe during testing |

## Deployment Procedure (PoC)

1. **Pre-requisite:** Solder terminal blocks, DB9 connectors, pin headers, and termination switches on both CANBed RP2040 boards.
2. Confirm OQ-1, OQ-2, OQ-3 from hardware documentation before writing any firmware.
3. Edit `nodes.csv` with 2 node entries (distinct node IDs, rooms, boards, GPIO lists).
4. Run `python3 generate_nodes.py` and review the CAN ID map output for duplicates.
5. Compile node firmware: `esphome compile nodes/node<id>.yaml` for each node.
6. Compile gateway firmware: `esphome compile gateway.yaml`.
7. Flash nodes via USB before bench assembly.
8. Assemble bench: connect both nodes and gateway on CAN bus, verify 120 Ω termination at each physical end.
9. Power nodes from 9–28 V supply. Power gateway from USB-C or DC.
10. Flash gateway via USB-C.
11. Open HA Developer Tools → Events, subscribe to `esphome.canbus_button` and `esphome.canbus_heartbeat`.
12. Execute validation per FR-9.1 through FR-9.6.

## Risks

| Risk                                                                            | Likelihood                     | Impact                           | Mitigation                                                                                     |
| ------------------------------------------------------------------------------- | ------------------------------ | -------------------------------- | ---------------------------------------------------------------------------------------------- |
| `on_frame` + `homeassistant.event` chain does not compile or behave as expected | High (untested path)           | High (blocks all HA integration) | Compile first; isolate the chain in a minimal test YAML before integrating full gateway config |
| Wrong INT pin (OQ-2) causes MCP2515 to silently fail                            | Medium                         | High                             | Verify from schematic before first compile; check for RX errors in ESPHome logs                |
| Wrong oscillator frequency (OQ-3) causes CAN timing errors                      | Medium                         | High                             | All devices will log error frames; confirm from board docs first                               |
| Missing or double termination causes reflections / bus errors                   | Low (easy to check physically) | Medium                           | Verify termination before powering                                                             |
| WiFi connectivity issues between gateway and HA                                 | Low                            | Medium                           | Ensure both are on same network; check ESPHome API connection logs                             |
