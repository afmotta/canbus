---
project_name: 'canbus'
user_name: 'Alberto'
date: '2026-06-05'
sections_completed: ['technology_stack', 'language_rules', 'framework_rules', 'testing_rules', 'code_quality', 'workflow', 'critical_rules']
status: 'complete'
rule_count: 32
optimized_for_llm: true
---

# Project Context for AI Agents

_Critical rules and patterns for implementing code in this project. Focus on unobvious details agents might otherwise miss._

---

## Technology Stack & Versions

- **ESPHome** — firmware framework (version pinned by your ESPHome installation; use latest stable)
- **RP2040** platform — `rpipico` board, ESPHome `rp2040` platform
- **ESP32-S3** platform — `esp32s3` variant, `esp-idf` framework (required for native TWAI CAN)
- **MCP2515** CAN controller — SPI, 16 MHz oscillator (CANBed RP2040 fixed board design)
- **W5500** Ethernet — Waveshare ESP32-S3-POE-ETH-8DI-8DO fixed pin mapping
- **PCA9554** I2C GPIO expander — address `0x20`, 8 digital outputs on gateway
- **CAN bus** — 125 kbps, 29-bit Extended IDs (ADR-0001 location-as-address)
- **Python 3** — `generate_nodes.py` code generation (stdlib only, no extra packages)
- **Home Assistant** — integration via ESPHome native API over PoE Ethernet

## Critical Implementation Rules

### C++ Lambda Rules (ESPHome `!lambda`)

- All lambdas receiving CAN frame data have access to `x` as `std::vector<uint8_t>` — always validate `x.size() >= N` before indexing any byte.
- Lambda return types are inferred — payload builders return `std::vector<uint8_t>`, `can_id()` returns `uint32_t`. Do not cast unnecessarily.
- `canbus_protocol.h` is the single source of truth for all constants and helpers. Never inline raw bit shifts or magic numbers in YAML lambdas — use the named functions.
- ESPHome globals are accessed as `id(global_name)` inside lambdas, not as plain variables.
- `to_string()` and `std::string()` are available in ESP-IDF lambdas (gateway); use them for `homeassistant.event` string conversions.

### Python (`generate_nodes.py`)

- Generates the node files in `nodes/` from `nodes.csv` (the node registry). `nodes/` is generated output — do not hand-edit it.
- Node files are now **minimal**: shared hardware config (SPI/CAN pins) and the standard 8-button set live in `common/base_node.yaml`, so each generated node carries only its identity (`node_name`/`node_id`/`debounce_ms`) plus `packages: base: !include ../common/base_node.yaml`.
- Uses stdlib only (`csv`, `pathlib`) — do not add external dependencies.
- The script validates registry entries (e.g. room/board ranges, globally unique `(room, board)`). Add new validations here, not in the template string.
- If `nodes.csv` is missing, the script seeds example rows (nodes 100 and 101) and exits before generating `nodes/` output.

### ESPHome Framework Rules

**Package / include system:**

- Shared config lives in `common/` as packages. Nodes include them via `packages:` + `!include`.
- The standard 8-button set is declared once in `common/base_node.yaml` (not per node file), using the parameterized form:
  `btn0: !include { file: ../common/button.yaml, vars: { button_index: "0", button_gpio: "24" } }`
- Node files declare only `node_name`, `node_id`, and `debounce_ms` in the top-level `substitutions:` block, before the `packages:` block.

**CAN bus filtering (gateway):**

- The gateway matches all frames of a given category using Extended-ID mask filtering: `can_id: 0x04000000` + `can_id_mask: 0x1C000000` catches all CAT_INPUT frames regardless of node.
- Category bits are bits 28:26 of the 29-bit Extended CAN ID. Mask `0x1C000000` matches category only.
- CAT_INPUT = 1 → base ID `0x04000000`; CAT_STATUS = 3 → base ID `0x0C000000`.

**`homeassistant.event` data:**

- Data values must be strings. Use `to_string(...)` or `std::string(char_ptr)` (e.g. `room: !lambda 'return to_string(id_room(can_id));'`).
- Attach a per-field `!lambda` to each data key that re-decodes directly from the frame vector `x`. This is the shipped gateway pattern (`firmware/gateway.yaml` CAT_INPUT handler) — **no globals**. A `!lambda` on the data field runs in the `on_frame` scope where `x` is in scope.
- The real constraint is narrower than "use globals": you cannot reference a variable declared in a *separate preceding* `lambda:` action, because the data block runs in its own action context. Re-decode in the field `!lambda` instead of staging.

**`on_multi_click` ordering:**

- Patterns MUST be ordered longest-first: triple → double → single → hold → hold_release (`button.yaml`, ADR-0012 single vocabulary). ESPHome matches the first satisfied pattern; shorter patterns shadow longer ones if listed first.
- A final `ON for at least X` timing entry fires WHILE the button is still held (no falling edge awaited) — this is how the `hold` event fires mid-press (ADR-0012 §1).
- `long_press`/`extra_long_press` do not exist (ADR-0012 §2): their patterns would match a hold too and fire duplicates. A long press is derived centrally (HA) from hold → hold_release; do not re-add those patterns to `button.yaml` or the constants to the header. Wire values 0x04/0x05 are deliberately unassigned (hold is 0x06/0x07) — do not reuse them for new event types; an old-firmware frame must decode as "unknown", not as a new gesture.

**Platform differences:**

- Nodes use `rp2040` + `rpipico` board; gateway uses `esp32` + `esp32s3` variant + `esp-idf`.
- Gateway requires `esp-idf` framework for native TWAI (`esp32_can` platform). Arduino framework does not support native TWAI on ESP32-S3.
- Nodes do NOT have WiFi or API — no OTA, no web server, no logger over network.

### Testing & Validation

- **No unit test framework** — ESPHome YAML is validated by `esphome compile`. The primary "test" is a successful compile.
- **Compile before flashing:** always run `esphome compile <node>.yaml` locally before flashing. The `on_frame` + `can_id_mask` + `homeassistant.event` chain in `gateway.yaml` has not yet been compiled/tested against hardware — treat it as unverified.
- **Code generation validation:** `generate_nodes.py` prints a CAN ID map on completion. Review it for duplicate IDs and unexpected CAN addresses before flashing any batch of nodes.
- **Hardware pin verification complete:** Story 1.2 resolved GPIO20→GPIO11 for MCP2515 INT pin and confirmed button GPIOs as GPIO20–GPIO27. See `firmware/README.md` for full details.

### Code Quality & Style Rules

**File naming:**

- Node configs: `node<id>.yaml` (e.g. `node100.yaml`) — generated output, one file per node.

**C++ header conventions (`canbus_protocol.h`):**

- Constants: `UPPER_SNAKE_CASE` (e.g. `CAT_INPUT`, `EVT_CLICK`, `PROTO_V1`).
- Functions: `snake_case` (e.g. `can_id()`, `button_payload()`, `event_type_str()`).
- All payload builder/decoder functions return or accept `std::vector<uint8_t>`.
- Mark all functions `inline` to avoid ODR violations across multiple includes.

**ESPHome YAML conventions:**

- ESPHome component IDs: `snake_case` (e.g. `can0`, `evt_room`, `tca9554_hub`).
- Substitution variable names: `snake_case` without `${}` in the substitutions block.
- Section headers use `# ---` comment dividers for readability in long YAML files.

**Python conventions:**

- `snake_case` for all identifiers. Constants `UPPER_SNAKE_CASE` (e.g. `FLOOR_LABELS`, `TEMPLATE`).
- Template strings use `{placeholder}` style — escape ESPHome `${...}` as `${{...}}` in the Python template.

**Comments:**

- YAML files: section-header comments (`# --- Section name ---`) are standard; inline comments only for non-obvious pin choices or hardware quirks.
- C++ header: function-level comments explain protocol byte positions, not obvious logic.

### Development Workflow Rules

**Node provisioning workflow (always in this order):**

1. Edit `nodes.csv` to add/update the node entry (node_id, room, board, location).
2. Run `python3 generate_nodes.py` to regenerate `nodes/`. Generated node files are minimal —
   all hardware config and the 8-button set come from `common/base_node.yaml`.
3. Compile: `esphome compile nodes/node<id>.yaml`.
4. Flash via USB: `esphome upload nodes/node<id>.yaml` before physical installation.
5. Nodes cannot be updated wirelessly after installation — flashing is a one-shot operation.

**Gateway workflow:**

- Gateway has OTA via ESPHome (`ota: platform: esphome`) and Ethernet — can be updated remotely.
- Always recompile gateway when `canbus_protocol.h` changes to keep constants in sync.

**Protocol changes:**

- `canbus_protocol.h` is shared by both nodes and gateway. Any protocol change requires reflashing ALL affected nodes (no OTA) — treat protocol as frozen unless absolutely necessary.
- **Versioning policy:** until the project is declared LIVE, `PROTO_V1` stays `0x01` and breaking payload changes are made in place — no version bump — because every node is reflashed in lock-step with the gateway (no fielded firmware to stay compatible with). **Declaring the project live is Alberto's explicit call.** Only after going live does a breaking payload change require incrementing the protocol version byte.
- **Post-LIVE evolution doctrine (ADR-0008):** once LIVE, the controller is the sole compatibility layer — it decodes every historical payload version, and changes are absorbed controller-side before any fielded node is touched. Nodes and bridges are updated *physically* (in-place USB reflash, which preserves `node_id`, or board swap) — never over the air. No CAN bootloader is built: `BOOTLOADER` stays a comment-level name reservation in `canbus_protocol.h` with no category value. A fleet-wide breaking change becomes a physical reflash campaign — see `docs/reflash-campaign-runbook.md`, gated by `docs/live-freeze-checklist.md`.

**Adding a new node type or new event:**

1. Add constants to `canbus_protocol.h` first.
2. Update `button.yaml` or `base_node.yaml` for shared node behavior (or create a new common package).
3. Update the `generate_nodes.py` template only if new per-node substitution variables are needed.
4. Update gateway `on_frame` handler and `event_type_str()` decoder.

### Critical Don't-Miss Rules

**NEVER do these:**

- **Never edit files in `nodes/` by hand.** They are generated output — all changes go through `nodes.csv` → `generate_nodes.py`. Shared config (SPI/CAN pins, the 8-button set) belongs in `common/base_node.yaml`, not in per-node files or the generator template.
- **Never reintroduce the flat `node_id` / 11-bit ID model.** ADR-0001 is accepted: room, board, button, and event live in the 29-bit Extended CAN ID for INPUT frames; payloads carry protocol version, values, and parameters.
- **Never assume HA event data fields are integers.** All fields in `esphome.canbus_button` and `esphome.canbus_heartbeat` are strings (`"7"`, not `7`). HA automation `event_data:` filters must use string values.
- **Never skip the `x.size()` guard in CAN frame lambdas.** Malformed or short frames will crash without it.
- **Never use Arduino framework on the gateway.** Native TWAI (`esp32_can`) requires `esp-idf`. Switching to Arduino silently breaks CAN.
- **Never put security-critical actuation on the CAN bus.** Door locks, alarm arming, or any safety-critical actuator must not be driven from this bus without first revisiting ADR-0010. The bus is unauthenticated by decision (the physical envelope is the trust boundary), so any injected frame's worst case must stay behavioral and transient — never a lock thrown or an alarm disarmed. Standing constraint on all future feature intake.

**Key non-obvious facts:**

- The gateway fires `homeassistant.event` with a per-field `!lambda` that re-decodes from the frame vector `x` directly (no globals). A variable set in a *separate preceding* `lambda:` action is not in scope inside the data block (separate action context) — but a `!lambda` on the data field itself runs in `on_frame` scope and can read `x`. This per-field re-decode is a deliberate design decision (gateway HA event firing approach); do not "fix" it toward globals or the internal-API single-lambda form.
- Click detection happens on the node, not the gateway. Multi-click timing uses ESPHome's `on_multi_click` which runs locally. Do not attempt to reconstruct click sequences from raw CAN events on the gateway.
- `MSG_BUTTON_EVENT` and `MSG_HEARTBEAT` both equal `0x01` — they are distinguished by the CAN ID category (CAT_INPUT vs CAT_STATUS), not the message type byte alone.
- Node ID `0` is valid — it is not a null/unset sentinel. Node IDs start at 0.
- The `debounce_ms` substitution applies to both `delayed_on` and `delayed_off` GPIO filters — it is not the same as `on_multi_click` timing thresholds, which are hardcoded in `button.yaml` (exception: the hold recognition threshold is the `hold_ms` substitution, default 800, ADR-0012 — fleet-wide it is also the derived long-press threshold).
- **Aliveness lives on the gateway in `protocol/node_health.h`** (pure logic, natively tested like `ha_arbitration.h`) — there is ONE staleness doctrine (3× heartbeat cadence = 90 s, `node_lost_timeout_ms`, shared with ADR-0006's sensor-staleness rule, ADR-0011 §1). Do not add a second staleness rule for nodes/bridges. Watch state is RAM-only and tracked for **mapped** nodes only. The gateway forwards aliveness to HA as **edge events** (`esphome.canbus_node_lost` / `canbus_node_recovered` / `canbus_node_error`) plus **aggregate entities** (`nodes_online` / `nodes_total` / `fallback_events_count` / `nodes_missing`) — never a per-heartbeat stream and never per-node entities on the ESP32 (ADR-0011 §2). Like every other gateway event, the new `canbus_node_*` data fields are strings.

---

## Usage Guidelines

**For AI agents:** Read this file before implementing any code. Follow all rules exactly. When in doubt about CAN ID vs payload semantics, re-read the CAN ID section. Never touch `nodes/` directly — it is generated from `nodes.csv`.

**For humans:** Update when hardware pins are verified, when protocol version bumps, or when new common packages are added. Remove rules that become obvious over time.

_Last updated: 2026-06-05_
