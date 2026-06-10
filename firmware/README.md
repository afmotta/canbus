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
(`firmware/packages/base_node.yaml`) and Story 1.4 (`firmware/tools/generate_nodes.py` template).

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

**Known-good version:** ESPHome 2026.5.0 — confirmed by successful `esphome compile gateway.yaml` (Story 3.2) and the Epic 2 node compiles.

> **Not enforced:** no YAML carries an `esphome: min_version:` constraint, so this version is recorded, not pinned — a different installed ESPHome will still build. Treat 2026.5.0 as the last validated baseline; add `esphome: min_version:` if a hard floor becomes necessary.

> **Note:** As of ESPHome 2026.1.0 the `api: password:` option was removed. The gateway uses
> API encryption instead (`api: encryption: key: !secret api_encryption_key`). Generate a key with
> `openssl rand -base64 32` and add it to `secrets.yaml`.
>
> **Migration — re-adopt in HA:** switching from `api: password:` to `api: encryption:` changes the
> gateway's API identity. A gateway already adopted in Home Assistant must be **deleted and re-added**
> in HA (Settings → Devices & Services → ESPHome) with the new encryption key — it will not reconnect
> on the old password entry.

---

## Onboarding: `secrets.yaml`

The gateway reads three secrets at config load. ESPHome resolves `!secret` from a
`secrets.yaml` next to the config file, so it lives in `firmware/gateway/` (the gateway is the
only secrets user). There is no pre-flight validation — if `secrets.yaml` is missing or any key
is absent, `esphome compile`/`run` **fails at config load** with a missing-secret error (ESPHome
default behavior). Copy `gateway/secrets.yaml.example` to `firmware/gateway/secrets.yaml` before
the first build:

| Key                  | Value                                            |
| -------------------- | ------------------------------------------------ |
| `wifi_ssid`          | WiFi network name                                |
| `wifi_password`      | WiFi password                                    |
| `api_encryption_key` | base64 key from `openssl rand -base64 32`        |

Nodes have no WiFi/API and require no secrets.

---

## ha_ready Arbitration Prototype (ADR-0003)

The gateway carries a prototype of ADR-0003's HA-readiness arbitration: HA proves liveness
(and that it runs the same binding manifest) by calling the `ha_readiness_heartbeat` API
service every 5 s; each button event forwarded to HA carries an `event_id` that HA must ACK
via `ha_ack_event` before the fallback timeout. When HA is not ready — API disconnected,
heartbeat stale, or manifest-hash mismatch — or an ACK is missed, the **fallback only logs**
(`FALLBACK ...` at WARN): no relays exist yet, and the binding manifest is stubbed by a
placeholder hash.

- HA-side counterpart: copy `gateway/ha_arbitration_automations.yaml` into Home Assistant.
- Observability: the gateway exposes a diagnostic **HA Ready** binary sensor, and the logs
  carry the tuning data: `ACK ... rtt=` (round-trip per event), `FALLBACK ... waited=`
  (actual fallback latency — `ack_timeout_ms` plus up to 250 ms sweep granularity), and
  `LATE ACK ... late=+` (an ACK landing after its fallback fired: the double-action window).
- Tuning (resolves ADR-0003 open item 2 empirically) via `gateway.yaml` substitutions:
  `ha_heartbeat_ttl_ms` (default 15000) and `ack_timeout_ms` (default 500); `manifest_hash`
  (default `dev-unbound`) must match the hash HA's heartbeat sends.
- Pure logic lives in `protocol/ha_arbitration.h`; native test:
  `g++ -std=c++17 -Wall -Wextra firmware/tests/test_ha_arbitration.cpp -o /tmp/arb && /tmp/arb`
