# Firmware

## Hardware Verification

Hardware open questions resolved from the official Longan Labs CANBed RP2040 V1.1 Eagle schematic pinned to commit `fdefed9e521864c67a05bf19a4e5046428b86662`.

### OQ-1: Button GPIO numbers (CANBed RP2040)

**Status:** Confirmed  
**Value:** GPIO20, GPIO21, GPIO22, GPIO23, GPIO24, GPIO25, GPIO26, GPIO27 — the 8 digital I/O pins
exposed on the 9×2 expansion header (J1). Wire external push-button switches (active low,
internal pull-up) to these pins.

> **⚠️ Template correction required:** The existing `generate_nodes.py` template uses
> GPIO2, GPIO3, GPIO4, GPIO5 as button placeholder defaults. GPIO2/3/4 are **wrong** —
> they are the SPI SCK/MOSI/MISO lines used internally by MCP2515 (confirmed by schematic).
> Update template defaults to use GPIO20–GPIO27 instead.

**Source:** CANBed RP2040 V1.1 Eagle schematic — `CANBED_RP2040_V11_EAGLE` repository,
GitHub (pinned): <https://github.com/Longan-Labs/CANBED_RP2040_V11_EAGLE/blob/fdefed9e521864c67a05bf19a4e5046428b86662/CANBed2040_V1.1.sch> — J1 header net connections confirm
8 GPIO lines with no external pull-up resistors (internal pull-up required on each line).

---

### OQ-2: MCP2515 INT pin (CANBed RP2040)

**Status:** Confirmed  
**Value:** GPIO11  
**Source:** CANBed RP2040 V1.1 Eagle schematic — `CANBED_RP2040_V11_EAGLE` repository,
GitHub (pinned): <https://github.com/Longan-Labs/CANBED_RP2040_V11_EAGLE/blob/fdefed9e521864c67a05bf19a4e5046428b86662/CANBed2040_V1.1.sch> — `INT` net explicitly
connects `U5(!INT)` (MCP2515 interrupt output) to `U2(GPIO11)` (RP2040).

> **⚠️ Template correction required:** The existing template assumes `can_int_pin: "GPIO20"`.
> This is **wrong** — GPIO20 is a general-purpose digital I/O header pin, not the INT line.
> Update to `can_int_pin: "GPIO11"`. An incorrect INT pin causes MCP2515 to fall back to
> polling mode, which will miss CAN frames under burst conditions at 125 kbps.

---

### OQ-3: Oscillator frequency (MCP2515 on CANBed RP2040)

**Status:** Confirmed  
**Value:** 16 MHz  
**Source:** CANBed RP2040 V1.1 Eagle schematic — `CANBED_RP2040_V11_EAGLE` repository,
GitHub (pinned): <https://github.com/Longan-Labs/CANBED_RP2040_V11_EAGLE/blob/fdefed9e521864c67a05bf19a4e5046428b86662/CANBed2040_V1.1.sch> — part `X1` (crystal
connected to MCP2515 OSC1/OSC2) has `value="16MHz"`.

> Existing assumption `can_clock: "16MHZ"` is **correct** — no change required.

---

## Complete MCP2515 SPI Pin Reference (CANBed RP2040 V1.1)

All values confirmed from V1.1 Eagle schematic. Use these in Story 2.1
(`firmware/common/base_node.yaml`) and Story 1.4 (`firmware/generate_nodes.py` template).

| Signal      | RP2040 GPIO | Net name | Template assumption | Correct?  |
| ----------- | ----------- | -------- | ------------------- | --------- |
| SPI SCK     | GPIO2       | SCK      | GPIO18              | ❌ Wrong   |
| SPI MOSI    | GPIO3       | MOSI     | GPIO19              | ❌ Wrong   |
| SPI MISO    | GPIO4       | MISO     | GPIO16              | ❌ Wrong   |
| MCP2515 CS  | GPIO9       | CANCS    | GPIO9               | ✅ Correct |
| MCP2515 INT | GPIO11      | INT      | GPIO20              | ❌ Wrong   |
| Oscillator  | —           | —        | 16 MHz              | ✅ Correct |

---

## ESPHome Version

**Pinned version:** ESPHome 2026.5.0 — confirmed by successful `esphome compile gateway.yaml` (Story 3.2) and the Epic 2 node compiles.

> **Note:** As of ESPHome 2026.1.0 the `api: password:` option was removed. The gateway uses
> API encryption instead (`api: encryption: key: !secret api_encryption_key`). Generate a key with
> `openssl rand -base64 32` and add it to `secrets.yaml`.
