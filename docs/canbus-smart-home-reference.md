# CAN Bus Smart Home — ESPHome Protocol & Implementation Reference

## Overview

A CAN bus-based wall button system for Alberto's fienile (barn conversion) in Pioltello. The house has 3 floors (ground: 9 rooms, first: 8 rooms, second: 2 rooms) with up to 100+ button boards, each with up to 6 buttons. The system uses ESPHome on RP2040 button nodes and an ESP32-S3 gateway, communicating over CAN bus at 125 kbps.

## Architecture

### Design principle: dumb nodes, smart gateway

The button boards are walled in and hard to reach after installation. The RP2040 boards have no WiFi, so no OTA updates. Therefore:

- **Nodes are frozen firmware.** They detect button clicks locally and send self-describing CAN frames. They do not know what any button "does."
- **The gateway is updatable.** It bridges CAN bus to Home Assistant via the ESPHome API over PoE Ethernet. It decodes CAN frames and fires HA events.
- **Home Assistant owns all logic.** What happens when a button is pressed is defined entirely in HA automations, which can be changed at any time.

### Hardware

**Button nodes:** Seeed Studio / Longan Labs CANBed RP2040 (SKU 102991596). An off-the-shelf CAN bus development board with RP2040 MCU, on-board MCP2515 CAN controller (SPI0, CS on GPIO9) and MCP2551 CAN transceiver. CAN interface via 4-pin screw terminal or DB9 connector, with switchable 120Ω termination resistor. Accepts 9–28V power input on the CAN connector (provides regulated 3.3V/1A). Exposes 8 digital I/O, 3 analog inputs, I2C (Grove), UART (Grove), and SPI. Up to 6 of the digital I/O pins are used for buttons. No WiFi, no OTA — flashed via USB (Micro-USB) before installation. ~$16 per board ($14 at 10+). Product link: https://www.seeedstudio.com/CANBed-RP2040-CAN-Bus-development-board-p-5262.html

**Gateway:** Waveshare ESP32-S3-POE-ETH-8DI-8DO. Connects to Home Assistant via PoE Ethernet. Uses the ESP32-S3's native TWAI CAN controller (GPIO2 TX, GPIO3 RX) with the board's built-in isolated CAN transceiver. Also exposes 8 optocoupler-isolated digital inputs (GPIO4–11) and 8 digital outputs (via PCA9554 I2C expander at 0x20) for local use. The board has a W5500 Ethernet chip (SPI: CLK=GPIO15, MOSI=GPIO13, MISO=GPIO14, CS=GPIO16, INT=GPIO12, RST=GPIO39), a buzzer (GPIO46), and a WS2812 RGB LED (GPIO38).

## CAN Protocol v1

### CAN ID (standard 11-bit)

```
Bit:  10  9 │ 8  7  6  5  4  3  2  1  0
      C   C │ N  N  N  N  N  N  N  N  N

C = Category (2 bits, 0-3)
N = Node ID  (9 bits, 0-511)
```

The CAN ID is intentionally generic. It carries no semantic meaning about rooms or buttons — only a flat sequential node identifier and a category for bus arbitration priority and hardware filtering. All semantic data (room, board, button index, event type) lives in the 8-byte payload, making the payload fully self-describing.

**Categories** (lower value = higher CAN bus priority):

| Value | Name       | Direction        | Purpose                        |
|-------|------------|------------------|--------------------------------|
| 0     | CAT_SYSTEM | bidirectional    | Emergency, errors              |
| 1     | CAT_INPUT  | node → gateway   | Button events                  |
| 2     | CAT_OUTPUT | gateway → node   | LED/relay commands, config     |
| 3     | CAT_STATUS | node → gateway   | Heartbeat, health              |

The gateway uses CAN mask filtering (`can_id_mask: 0x600`) to match all messages of a given category regardless of node ID.

### Data payload (8 bytes)

**Button event** (CAT_INPUT):

```
Byte 0: Protocol version (0x01)
Byte 1: Message type (0x01 = MSG_BUTTON_EVENT)
Byte 2: Button index (0–5)
Byte 3: Event type
         0x01 = click
         0x02 = double_click
         0x03 = triple_click
         0x04 = long_press (1–3 seconds)
         0x05 = extra_long_press (3+ seconds)
Byte 4: Room ID (0–255)
Byte 5: Board ID (0–255)
Byte 6–7: Reserved (0x00)
```

**Heartbeat** (CAT_STATUS, sent every 30 seconds):

```
Byte 0: Protocol version (0x01)
Byte 1: Message type (0x01 = MSG_HEARTBEAT)
Byte 2: Uptime in hours (uint8, wraps at 255)
Byte 3: Button states bitmask (current GPIO states)
Byte 4: Error flags (0x00 = healthy, 0x01 = CAN TX fail, 0x02 = bus off)
Byte 5: Room ID
Byte 6: Board ID
Byte 7: Reserved (0x00)
```

### Why room/board are in the payload (not just the CAN ID)

ESPHome's `on_frame` CAN trigger provides the data bytes (`x`) but does not cleanly expose the received CAN ID as a lambda variable. When the gateway uses mask-based filtering to match all button events at once, it cannot decode which node sent the message from the CAN ID alone. Embedding room and board in the payload makes the frame self-describing and avoids the need for a custom ESPHome component. It also simplifies CAN trace debugging.

## Project file structure

```
esphome_canbus/
├── common/
│   ├── canbus_protocol.h    # C++ header: all constants, CAN ID helpers, payload builders/decoders
│   ├── base_node.yaml       # Shared node package: SPI, MCP2515, heartbeat, output command listener
│   └── button.yaml          # Per-button package: GPIO + on_multi_click with 5 event types
├── gateway.yaml             # Gateway config for Waveshare ESP32-S3-POE-ETH-8DI-8DO
├── generate_nodes.py        # Python script: reads nodes.csv, generates per-node YAML configs
├── nodes.csv                # Node registry: node_id, floor, room, board, location, gpio_list
└── nodes/                   # Generated node YAML files (one per board)
    ├── node000.yaml
    ├── node001.yaml
    └── ...
```

### Why the C++ header exists

ESPHome `!lambda` blocks are inline C++. Without the header, every lambda would contain raw bit shifts and magic numbers (e.g. `return {0x01, 0x01, ${button_index}, 0x01, 0x00, 0x00, 0x00, 0x00};`). The header provides named constants (`EVT_CLICK`, `CAT_INPUT`) and helper functions (`can_id()`, `button_payload()`) so that lambdas are one-liners. It also provides decoder functions (`payload_room()`, `event_type_str()`) used by the gateway. Both nodes and gateway include the same header, so the protocol definition cannot drift.

### Per-button package pattern

Each physical button is added to a node config via ESPHome's `!include` with `vars`:

```yaml
packages:
  btn0: !include { file: ../common/button.yaml, vars: { button_index: "0", button_gpio: "2" } }
  btn1: !include { file: ../common/button.yaml, vars: { button_index: "1", button_gpio: "3" } }
```

The `button.yaml` template creates a `binary_sensor` with `on_multi_click` handling all 5 event types. Click detection runs locally on the node (not on the gateway) because multi-click timing requires consistent millisecond-level precision that would be affected by CAN bus latency. The timing thresholds are compile-time constants in ESPHome's `on_multi_click` and cannot be changed at runtime.

Multi-click patterns are ordered longest-first (triple → double → single → long → extra long) so the longest sequence matches before shorter ones.

### CANBed RP2040 SPI pin mapping

The MCP2515 CAN controller on the CANBed RP2040 is connected via SPI0. These pins are fixed by the board design (set as defaults in the generator, overridable via substitutions for other boards):

| Function | GPIO | Source |
|----------|------|--------|
| SPI CS   | GPIO9  | Confirmed — Longan Labs Arduino examples state `SPI_CS_PIN = 9` |
| SPI SCK  | GPIO18 | RP2040 SPI0 default |
| SPI MOSI | GPIO19 | RP2040 SPI0 default |
| SPI MISO | GPIO16 | RP2040 SPI0 default |
| INT      | GPIO20 | Needs verification from board schematic |
| Clock    | 16MHZ  | Longan Labs MCP_CAN library defaults to 16MHz oscillator |

The board exposes 8 digital I/O and 4 analog inputs (usable as digital) on the main 9x2 header, plus Grove connectors for I2C (Wire1) and UART (Serial1). The exact GPIO numbers for button-usable pins need to be confirmed from the pinout diagram (https://www.longan-labs.cc/media/wysiwyg/CAN-Bus/CANBed/Details_of_CANBed-04.png).

Note: the board ships as a kit with unsoldered through-hole components (terminal blocks, DB9 connector, pin headers, 120Ω termination switch). These must be soldered before use.

### Node config generation

`generate_nodes.py` reads `nodes.csv` and produces one YAML file per board. The CSV schema:

```
node_id,floor,room,board,location,gpio_list
0,0,0,0,"Hallway entrance","2,3,4,5"
1,0,1,0,"Kitchen left","2,3,4,5,6,7"
10,1,9,0,"Master bedroom door","2,3,4,5"
```

- `node_id` (0–511): flat CAN bus address, assigned manually. You can reserve ranges by convention (e.g. 0–49 ground floor, 50–99 first floor).
- `floor`: metadata only (for display and grouping), not encoded in CAN ID.
- `room`, `board`: carried in the payload so the gateway and HA know the physical location.
- `gpio_list`: comma-separated GPIO pin numbers for buttons on that board.

The generator validates ranges, detects duplicate node IDs, and prints a CAN ID map grouped by floor.

## Gateway → Home Assistant integration

### Events fired

The gateway fires two HA event types:

**`esphome.canbus_button`** — on every button press:
```yaml
event_data:
  room: "7"       # string
  board: "2"      # string
  button: "3"     # string (0-5)
  event: "click"  # click | double_click | triple_click | long_press | extra_long_press
```

**`esphome.canbus_heartbeat`** — every 30 seconds per node:
```yaml
event_data:
  room: "7"
  board: "2"
  uptime: "42"    # hours
  errors: "0"     # 0 = healthy
```

### HA services exposed

**`esphome.canbus_gateway_canbus_send_output`** — send a command to a node:
- `node_id`: int (0–511)
- `subtype`: int (message sub-type)
- `param1`, `param2`: int (command parameters)

**`esphome.canbus_gateway_canbus_send_config`** — send a config parameter:
- `node_id`: int (0–511)
- `key`: int (config key)
- `value`: int (uint16 value)

### Example HA automation

```yaml
automation:
  - alias: "Kitchen light toggle"
    trigger:
      - platform: event
        event_type: esphome.canbus_button
        event_data:
          room: "1"
          board: "0"
          button: "0"
          event: "click"
    action:
      - service: light.toggle
        target:
          entity_id: light.kitchen_main
```

## Known limitations and future work

- **No OTA for nodes.** RP2040 boards without WiFi must be flashed via USB. A CAN-bus bootloader protocol (using a reserved category) could enable over-the-wire firmware updates from the gateway, but this has not been implemented.
- **Click timing is compile-time.** ESPHome's `on_multi_click` timing values are baked into firmware. The CAN config message infrastructure is wired up in the protocol but cannot currently change click thresholds at runtime without a custom ESPHome component.
- **Not yet compiled/tested.** The YAML and C++ have been designed but not compiled against ESPHome. The `on_frame` + `can_id_mask` + `homeassistant.event` chain in the gateway is the most likely area for issues.
- **Single gateway.** The current setup has one gateway. For very long bus runs, per-floor gateways could use the category mask filtering to partition traffic.
- **Node health dashboard.** The heartbeat events are fired to HA but no dashboard or alerting has been built to track node online/offline status.
