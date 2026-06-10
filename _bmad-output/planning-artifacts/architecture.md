---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
lastStep: 8
status: 'complete'
completedAt: '2026-05-31'
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-canbus-2026-05-29/prd.md
  - _bmad-output/project-context.md
  - docs/canbus-smart-home-reference.md
workflowType: 'architecture'
project_name: 'canbus'
user_name: 'Alberto'
date: '2026-05-30'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements (9 groups):**

- FR-1–3: Node firmware — button detection (5 event types, up to 6 buttons), CAN transmission via MCP2515/SPI0, 30-second heartbeat
- FR-4: Protocol header (`canbus_protocol.h`) as single source of truth for all CAN constants and helpers; included by both node and gateway firmware
- FR-5–7: Gateway firmware — mask-based CAN reception, HA event forwarding (WiFi for PoC), connectivity
- FR-8: Code generation — `generate_nodes.py` reads `nodes.csv`, produces per-node YAML; `nodes/` is generated output only; `nodes.csv` is the source of truth for physical hardware
- FR-9: Validation — 10 event-type combinations (5 types × 2 nodes) must produce correctly decoded HA events

**Non-Functional Requirements:**

- NFR-1: Compile-first gate — both platforms must compile before hardware testing; failed compile = blocking defect
- NFR-2: Lambda safety — `if (x.size() < 8) return;` guard mandatory in all CAN frame receive lambdas (minimum bound is 8, not just non-zero; this value must be a named constant in `canbus_protocol.h`, not inlined)
- NFR-3: Protocol as single source of truth — no constants duplicated outside `canbus_protocol.h`
- NFR-4: Gateway must use `esp-idf` framework (Arduino incompatible with native TWAI on ESP32-S3)
- NFR-5: Node isolation — no WiFi, no OTA, no ESPHome API; intentional and permanent
- NFR-6: CAN bus speed uniformity — all devices must use 125 kbps
- NFR-7: Bus termination — exactly two 120 Ω resistors, one at each physical end
- NFR-8: Observability — the gateway lambda chain must produce ESPHome log output confirming each event fired and staged; silent failure in the on_frame→global→homeassistant.event chain is not detectable without explicit logging
- NFR-9: Validation must be logged and repeatable, not eyeball-only; HA Developer Tools event log must be captured as an artifact for each of the 10 acceptance combinations to provide a regression baseline before production hardware swap

**Scale & Complexity:**

- PoC scope: 2 nodes + 1 gateway, bench setup
- Production intent: 100+ nodes, 3 floors, 19 rooms, single gateway
- Primary domain: Embedded IoT firmware (ESPHome) + Home Assistant integration
- Complexity level: Medium (embedded cross-platform, protocol design, irreversible deployment constraints)
- Estimated architectural components: 4 (node firmware, gateway firmware, CAN protocol layer, HA integration)

### Technical Constraints & Dependencies

- **RP2040 nodes**: No WiFi, no OTA, flashed once via USB before wall installation. Firmware is permanent. Cost of a post-installation firmware bug is physical wall access — treat the protocol as a hardware interface, not software.
- **Protocol versioning is mandatory on day one.** `PROTO_V1 = 0x01` must be in `canbus_protocol.h` before the PoC build. The PoC should validate the exact wire format, not discover it. A versioned CAN frame spec (exact byte positions, frame sizes, ID bit layout) must be a PoC deliverable, not a narrative.
- **ESPHome `on_frame` constraint**: CAN ID not cleanly accessible in mask-filtered lambdas → room/board must live in payload.
- **ESPHome `homeassistant.event` constraint**: Lambda-local variables not in scope for data blocks → all values must be staged into ESPHome globals first. Global variable type, declaration location, and flush/reset semantics must be explicitly specified in implementation.
- **`esp-idf` framework required on gateway**: Arduino framework does not support native TWAI on ESP32-S3.
- **Protocol freeze risk**: Any breaking change to `canbus_protocol.h` requires reflashing ALL nodes (no OTA). Protocol must be versioned and treated as frozen after PoC sign-off.
- **PoC gateway vs production gateway are different boards**: PoC uses Waveshare ESP32-S3-RS485-CAN (WiFi; CAN TX=GPIO15, RX=GPIO16). Production target is ESP32-S3-POE-ETH-8DI-8DO (PoE Ethernet; different CAN GPIO mapping, W5500 Ethernet, PCA9554 I/O expander). This is not a pin-mapping swap — these boards differ in BSP configuration, power domains, and boot behavior. The architecture must explicitly state what is validated on PoC hardware and what requires re-validation on production hardware.
- **`nodes.csv` is source-of-truth for physical hardware**: Schema changes, validation rules, and version history must be managed with the same discipline as `canbus_protocol.h`. A bad CSV commit that generates a broken YAML for a wall-mounted node is equivalent to a bad protocol change.
- **ESPHome version must be pinned**: MCP2515 component behavior and `canbus:` YAML key names changed between ESPHome 2023.x and 2024.x. An unpinned version means compile behavior floats between environments.
- **Open hardware questions blocking compile**: Button GPIO numbers (OQ-1), MCP2515 INT pin (OQ-2), oscillator frequency (OQ-3). Note: if OQ-2 is wrong, MCP2515 silently falls back to polling mode, which will miss frames under button burst conditions at 125 kbps.
- **`can_id_mask` behavior differs between MCP2515 (nodes) and TWAI (gateway)**: ESPHome's `canbus` component abstracts this, but the mask semantics must be verified against actual ESPHome component behavior before assuming frame filtering works identically on both platforms.

### Cross-Cutting Concerns Identified

1. **CAN protocol versioning** — `canbus_protocol.h` is shared across all firmware. Any breaking change has fleet-wide impact with no rollback path on nodes. Protocol must be a formally versioned wire spec before installation begins.
2. **Lambda safety** — `if (x.size() < 8) return;` guard must appear in every CAN frame receive lambda. The minimum size value must be a named constant, not inlined.
3. **String-only HA event data** — all `homeassistant.event` data fields must be strings. The exact string format for each field (e.g. raw integer as string: `"1"` not `"room_1"`) must be specified and consistent so HA automations can match reliably.
4. **Global staging pattern** — all values used in `homeassistant.event` blocks must be staged into ESPHome globals first. Variable types and flush semantics must be explicitly specified.
5. **Platform framework split** — nodes use `rp2040` platform; gateway must use `esp-idf`. Framework confusion is a silent, hard-to-debug failure mode.
6. **Hardware verification gates** — three open questions (OQ-1, OQ-2, OQ-3) must be resolved from physical documentation before any firmware can compile correctly.
7. **Observability gap in the untested chain** — the on_frame→global→homeassistant.event path has no exception surface. Logging must be explicit within the chain; silent failures are undetectable otherwise.
8. **CAN bus topology** — resolved in structure by ADR-0005 (accepted 2026-06-10): a segmented multi-bus (backbone + per-zone secondaries, strict loop-free tree, 125 kbps everywhere) coupled by store-and-forward software bridges (`firmware/bridge/bridge.yaml`); a single trunk-and-spur is not viable for this house. The segment count and cable-budget/zone sketch remain ADR-0005 open item 1 and must precede installation. CAN ID priority still cannot be retrofitted after protocol freeze; under the current flat `[category:4][node_id:13][reserved:12]` layout, ADR-0004 decision D3 accepts the within-category `node_id` priority coupling as a known, benign limitation for this protocol.
9. **Commissioning procedure gap** — no procedure exists for registering, assigning an ID to, and verifying a new node on the bus before wall installation. A commissioning checklist is a required PoC deliverable given the no-OTA constraint.
10. **Single gateway = single point of failure** — if the gateway is unavailable, all button events are silently dropped. This is an accepted PoC constraint but must be a stated architectural decision, not an implicit one.

## Starter Template Evaluation

### Primary Technology Domain

Embedded IoT firmware — ESPHome (RP2040 + ESP32-S3) with Python code generation.
No CLI scaffold applies. The project foundation is the existing ESPHome file structure.

### Existing Project Foundation

The codebase in `docs/esphome_canbus/` serves as the project starter. It is not a
generated scaffold — it is an authored structure that embodies the core architectural
decisions.

**Architectural Decisions Already Established:**

**Protocol Layer:**
`common/canbus_protocol.h` — C++ header included by both node and gateway firmware.
Single source of truth for all CAN constants, frame builders, and decoders. Inline
functions only (no ODR violations across multiple includes).

**Shared Config Mechanism:**
ESPHome `packages:` + `!include { file, vars }` pattern for shared node behavior.
`common/base_node.yaml` — SPI, MCP2515, heartbeat, AND the standard 8-button set
(`btn0`–`btn7`), hardcoded once and shared across all nodes. SPI/CAN pins are hardcoded
here too (no per-node pin substitutions). `common/button.yaml` — parameterized
per-button package (`button_index`, `button_gpio`), included 8× by `base_node.yaml`.

**Code Generation Pipeline:**
`generate_nodes.py` (Python stdlib only) reads `nodes.csv` → generates `nodes/*.yaml`.
`nodes.csv` is the source of truth for physical hardware; `nodes/` is generated output.
Because shared config (SPI/CAN pins, the 8-button set) now lives in `base_node.yaml`, each
generated node file is **minimal** — only `node_name`/`node_id`/`debounce_ms` substitutions
plus `packages: base: !include ../common/base_node.yaml`. All nodes are identical apart from
their identity.

**Platform Split:**
Node configs: `rp2040` platform, `rpipico` board.
Gateway config: `esp32` platform, `esp32s3` variant, `esp-idf` framework.
Separate top-level YAML files; no shared platform config possible.

### Structural Decision

**Current location:** `docs/esphome_canbus/` (firmware embedded under docs/)

**Decision:** Move firmware to a top-level directory (e.g. `firmware/`) before the
PoC build begins. Rationale: `docs/` implies documentation; `nodes.csv` and the
generated `nodes/` directory are hardware source of truth and build output respectively.
Keeping them under `docs/` creates a semantic mismatch and may confuse future tooling.

**Note:** Directory restructure is the first implementation story — complete before
any PoC firmware is compiled.

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**

- HA event firing via `homeassistant.event:` YAML action, no global staging — affects all gateway on_frame handlers
- Node ID space allocation — affects nodes.csv schema and all future provisioning
- canbus_protocol.h retained — affects ESPHome includes config in every YAML file
- Firmware directory restructure — must precede any compile

**Important Decisions (Shape Architecture):**

- HA event field format (raw integers as strings)
- Heartbeat disposition for PoC
- ESPHome secrets management pattern
- PoC sign-off criteria

**Deferred Decisions (Post-PoC):**

- Room name translation (integer → human-readable); HA templates handle if needed
- Production gateway board validation (WiFi → PoE Ethernet re-validation)
- Node health dashboard and aliveness alerting
- CAT_OUTPUT command implementation (gateway → node)

### Protocol & State Management

**Global staging: eliminated.**
The gateway fires Home Assistant events using the ESPHome `homeassistant.event:` YAML
action, guarded by an `if:` / `condition:` block. Each event-data field is a `!lambda`
that decodes directly from the CAN frame (`x`) via the `canbus_protocol.h` helpers — no
values are staged through ESPHome globals.

Rationale: the `homeassistant.event:` action is documented, stable across ESPHome
versions, and matches the project's `on_frame` guard convention (clean action lambdas,
validity checks in the `condition:`). An earlier design mandated a single-lambda direct
internal-API call (`api::global_api_server->send_homeassistant_action`); that was reversed
on 2026-06-02 (Alberto) because the internal API is undocumented and version-coupled,
whereas the YAML action carries neither risk while still avoiding global staging.

**Node ID space allocation:**

| Range | Assignment |
| --- | --- |
| 0–99 | Core / infrastructure devices (gateway, future hubs) |
| 100–199 | Ground floor nodes (9 rooms) |
| 200–299 | First floor nodes (8 rooms) |
| 300–399 | Second floor nodes (2 rooms) |
| 400–511 | Reserved / future expansion |

Note: floor is derivable from node ID range — a conscious, documented override of the
"no semantic meaning in CAN ID" principle. Trade-off accepted for readable CAN traces.
Node ID assignment within each range is flat sequential (100, 101, 102…), not
room-encoded.

**Heartbeat disposition (PoC):**
Gateway logs heartbeat frames via ESPHome logger only. No `esphome.canbus_heartbeat`
HA event fired in the PoC. Revisit for production when node health monitoring is needed.

**canbus_protocol.h: retained.**
Future message types (temperature sensors, presence sensors) will add categories,
message subtypes, and payload structures that must stay in sync across all nodes and
the gateway. The header is the right mechanism for this. Removing it now and re-adding
it later has higher cost than the include path overhead. The `generate_nodes.py`
generator injects the `includes:` directive into all node configs automatically.

### Credentials & Secrets Management

`secrets.yaml` at firmware root (gitignored). Referenced via `!secret` in all configs.
Contains: `wifi_ssid`, `wifi_password`, `ha_api_key`. Standard ESPHome pattern.

### HA Integration Interface

**Event field format:**
All `homeassistant.event` data values are strings (ESPHome constraint). Fields:

- `room`: raw integer as string — `"7"` (not `"room_7"`)
- `board`: raw integer as string — `"2"`
- `button`: raw integer as string — `"0"`–`"5"`
- `event`: human-readable — `"click"`, `"double_click"`, `"triple_click"`, `"long_press"`, `"extra_long_press"`

Room name translation to human-readable strings is deferred; HA templates or helpers
handle mapping if needed.

### Firmware Build & Deployment

**ESPHome version:** latest stable at time of first compile. Pin the version immediately
after first successful compile. Version pin noted in `README` at firmware root. All
subsequent compiles use the pinned version.

**Directory structure:** firmware lives at `firmware/` (project root), not
`docs/esphome_canbus/`. Directory restructure is Story 1 — execute before any compile.

**PoC sign-off criteria:**

1. All 10 acceptance combinations (5 event types × 2 nodes) produce correctly decoded `esphome.canbus_button` events in HA Developer Tools.
2. Each of the 10 events is captured as a logged artifact (screenshot or export of HA event log) — not eyeball-only. This artifact is the regression baseline before production hardware swap.
3. Zero CAN error frames in ESPHome gateway logs during the validation run.

**Commissioning procedure (PoC, 2-node bench):**

1. Edit `nodes.csv` with the node entry (node_id, room, board, location)
2. Run `python3 generate_nodes.py` — review CAN ID map for duplicates. Generated node files are minimal; all hardware config and the 8-button set come from `base_node.yaml`
3. `esphome compile nodes/node<id>.yaml` — must pass before flashing
4. Flash via USB: `esphome upload nodes/node<id>.yaml`
5. Power node; verify at least one heartbeat visible in ESPHome gateway log within 60s

### Decision Impact Analysis

**Implementation sequence (Story ordering implications):**

1. Directory restructure (`docs/esphome_canbus/` → `firmware/`)
2. Verify OQ-1/OQ-2/OQ-3 from hardware documentation; update `nodes.csv` and `canbus_protocol.h` accordingly
3. Compile node firmware (compile gate before any hardware connection)
4. Compile gateway firmware
5. Flash nodes, assemble bench, run validation

**Cross-component dependencies:**

- `canbus_protocol.h` is a compile-time dependency of both node and gateway firmware. Any change requires recompiling both.
- A change to shared node behavior (pins, the 8-button set) is made once in `common/base_node.yaml` and applies to all nodes. A `nodes.csv` schema/identity change requires re-running `generate_nodes.py` to regenerate the (minimal) node files.
- Gateway HA event firing uses the documented `homeassistant.event:` YAML action; ESPHome version is still pinned after first compile for reproducibility, but no internal-API re-validation is required on upgrade.
- The Extended-ID field layout is permanent after LIVE — changing it requires reflashing
  affected nodes. `(room, board)` collisions are address collisions and must be prevented by
  registry validation/commissioning checks.

## Implementation Patterns & Consistency Rules

### Critical Conflict Points

8 areas where AI agents could make different choices and break compatibility.

### Lambda Safety Pattern

Every `on_frame` handler on both nodes and gateway MUST begin with the relevant frame size
guard. Minimum payload lengths are defined in `canbus_protocol.h` per frame type, such as
`INPUT_PAYLOAD_MIN`, `STATUS_PAYLOAD_MIN`, and `CONFIG_PAYLOAD_MIN`.

**Correct:**

```cpp
if (x.size() < STATUS_PAYLOAD_MIN) return;
```

**Wrong — do not use these forms:**

```cpp
if (x.empty()) return;           // wrong bound for most frames
if (x.size() == 0) return;       // wrong bound for most frames
if (x.size() < 8) return;        // magic number — use the named per-frame minimum
```

On unexpected frame size: return silently. Do not log, do not fire an error event.
Rationale: malformed frames on a busy bus should not produce noise in the HA log.

### Protocol Constants Pattern

All CAN ID construction, payload building, and frame decoding MUST use named constants
and functions from `canbus_protocol.h`. Raw hex values and bit shifts are forbidden
in YAML lambdas.

**Correct:**

```cpp
// CAN ID construction
return can_id(CAT_INPUT, ${node_id});

// Payload construction
return button_payload(${button_index}, EVT_CLICK, ${room_id}, ${board_id});

// Event type string on gateway
std::string evt = event_type_str(x[3]);
```

**Wrong:**

```cpp
return (1 << 9) | ${node_id};    // raw bit shift
return {0x01, 0x01, ...};        // magic bytes
if (x[3] == 1) evt = "click";    // magic number
```

### Gateway on_frame Handler Pattern

Each gateway frame category is one `on_frame` filter entry. Payload validity is checked
in an `if:` / `condition:` lambda; the action branch logs (NFR-8) and, for button frames,
fires `esphome.canbus_button` via the `homeassistant.event:` action. No globals, no value
staging between actions.

**Structure:**

```yaml
on_frame:
  - can_id: 0x04000000
    can_id_mask: 0x1C000000
    use_extended_id: true
    then:
      - if:
          condition:
            lambda: 'if (x.size() < INPUT_PAYLOAD_MIN) return false; return x[0] == PROTO_V1;'
          then:
            - lambda: |-
                ESP_LOGI("gw", ...);   // log decoded values first (NFR-8)
            - homeassistant.event:
                event: esphome.canbus_button
                data:                  // each field a !lambda decoding from can_id; all values strings
                  room: !lambda 'return to_string(id_room(can_id));'
                  # board / button / event likewise
```

The size guard `if (x.size() < <PAYLOAD_MIN>) return false;` is the first statement of the
`condition:` lambda — before any byte is indexed. One `on_frame` handler per CAN category:
CAT_INPUT (button events → HA) and CAT_STATUS (heartbeat — log only in PoC), using
Extended-ID category masks.

### ESPHome Globals Usage Rule

ESPHome globals are **not used for HA event staging** (eliminated in architectural
decisions). Globals are still permitted for:

- CAN error flag tracking (MCP2515 error state, as required by FR-3.2)
- Any future state that genuinely needs to persist between `on_frame` calls

An ESPHome global should never be introduced solely to pass a value from one action
to the next within a single `on_frame` handler. If that pattern appears, replace it
by decoding directly from `can_id` and/or `x` in each `!lambda` (e.g. per-field in the
`homeassistant.event:` data block).

### YAML Structure Conventions

**Block ordering in node configs (always in this order):**

1. `substitutions:` — must be first; all variables declared here
2. `packages:` — shared packages included here, after substitutions
3. Platform config (`esphome:`, `rp2040:`, `spi:`, `canbus:`)
4. Component-specific blocks

**Section headers:** use `# --- Section name ---` comment dividers for any YAML
file over ~50 lines. Do not use inline comments except for non-obvious pin choices
or hardware-specific quirks.

**Button package inclusion:**

The standard 8-button set is declared once in `common/base_node.yaml` (not per node file):

```yaml
# common/base_node.yaml
packages:
  btn0: !include { file: ../common/button.yaml, vars: { button_index: "0", button_gpio: "24" } }
  btn1: !include { file: ../common/button.yaml, vars: { button_index: "1", button_gpio: "23" } }
  btn2: !include { file: ../common/button.yaml, vars: { button_index: "2", button_gpio: "22" } }
  btn3: !include { file: ../common/button.yaml, vars: { button_index: "3", button_gpio: "21" } }
  btn4: !include { file: ../common/button.yaml, vars: { button_index: "4", button_gpio: "25" } }
  btn5: !include { file: ../common/button.yaml, vars: { button_index: "5", button_gpio: "20" } }
  btn6: !include { file: ../common/button.yaml, vars: { button_index: "6", button_gpio: "19" } }
  btn7: !include { file: ../common/button.yaml, vars: { button_index: "7", button_gpio: "10" } }
```

Button index and GPIO are always strings in the `vars` block (ESPHome substitution
variables are strings). The template casts them where needed.

### Code Generation Discipline

Node files in `firmware/nodes/` are generated output and minimal. **Never edit them by
hand.** To add or change a node:

1. Edit `firmware/nodes.csv` (node_id — the node's only flashed identity — plus room, board, location).
2. Run `python3 generate_nodes.py`.
3. Review the CAN ID map output for duplicate IDs before compiling.

Shared behavior (SPI/CAN pins, the 8-button set, heartbeat) belongs in `common/base_node.yaml`,
not in individual node files or the generator template — that is what keeps the generated node
files minimal and all nodes identical apart from identity.

### Node ID Assignment Rule

Node IDs must be assigned from the correct floor range:

| Range | Floor |
| --- | --- |
| 0–99 | Infrastructure (gateway etc.) |
| 100–199 | Ground floor |
| 200–299 | First floor |
| 300–399 | Second floor |

Assign IDs sequentially within each range. Do not skip IDs without a comment in
`nodes.csv` explaining the gap. The `generate_nodes.py` validator must reject IDs
outside 0–399 or duplicates.

### Naming Conventions

- **ESPHome component IDs:** `snake_case` (e.g. `can0`, `btn_0`, `can_input_handler`)
- **ESPHome substitution variables:** `snake_case` without `${}` in the block
- **C++ constants:** `UPPER_SNAKE_CASE` (e.g. `CAT_INPUT`, `EVT_CLICK`, `CAN_FRAME_SIZE`)
- **C++ functions:** `snake_case` (e.g. `can_id()`, `button_payload()`, `event_type_str()`)
- **Python identifiers:** `snake_case`; constants `UPPER_SNAKE_CASE`
- **Generated node filenames:** `node{id}.yaml` (e.g. `node100.yaml`) — one per node

### Enforcement Guidelines

**All AI agents MUST:**

- Read `canbus_protocol.h` before writing any lambda that constructs or decodes a CAN frame
- Check `firmware/nodes.csv` / the live commissioning registry before assigning a new `(room, board)`
- Verify the relevant `x.size() < *_PAYLOAD_MIN` guard is the first check before any payload byte is accessed (first line of the lambda for nodes; first statement of the `condition:` lambda for the gateway)
- On the gateway, fire HA events via the `homeassistant.event:` action with `if:`/`condition:` guards — never introduce globals for event staging
- Compile with `esphome compile` before reporting a task complete; a failed compile is not a completed story

**Anti-patterns to flag in review:**

- Raw hex or bit shifts in YAML lambdas (use protocol header)
- Per-node hardware config (SPI/CAN pins, button packages) instead of putting shared config in `common/base_node.yaml`
- Any hand-edit of files under `firmware/nodes/` (they are generated — change `nodes.csv` and regenerate)
- `x.size() == 0` or `x.empty()` as the frame guard (wrong bound)
- ESPHome global introduced solely for event staging

## Project Structure & Boundaries

### Complete Project Directory Structure

```text
canbus/                                  # project root
├── .gitignore
├── README.md
├── docs/
│   ├── canbus-smart-home-reference.md   # protocol & hardware reference
│   └── esphome_canbus/                  # DEPRECATED — contents moved to firmware/
├── firmware/                            # all ESPHome firmware (moved from docs/)
│   ├── secrets.yaml                     # gitignored — WiFi + HA API credentials
│   ├── secrets.yaml.example             # template committed to repo
│   ├── nodes.csv                        # node registry — source of truth for hardware
│   ├── generate_nodes.py                # CSV → per-node YAML generator
│   ├── gateway.yaml                     # gateway firmware config
│   ├── common/
│   │   ├── canbus_protocol.h            # protocol constants & helpers (shared)
│   │   ├── base_node.yaml               # shared node package: SPI, MCP2515, heartbeat, 8-button set
│   │   └── button.yaml                  # per-button parameterized package
│   └── nodes/                           # GENERATED (minimal files) — never edit directly
│       ├── node100.yaml                 # ground floor nodes start at 100
│       ├── node101.yaml
│       └── ...
└── _bmad-output/                        # planning artifacts (BMad)
    └── planning-artifacts/
        ├── architecture.md
        └── prds/
```

**Gitignored:**

- `firmware/secrets.yaml` — credentials
- `firmware/.esphome/` — ESPHome build cache (auto-created on compile)

**Committed (including generated):**

- `firmware/nodes/*.yaml` — generated node configs are committed so diffs are
  reviewable when `nodes.csv` changes. Generated ≠ temporary.

### Architectural Boundaries

**Node firmware boundary** (`firmware/common/` + `firmware/nodes/`)

- Input: GPIO button press events (hardware)
- Output: CAN frames over MCP2515/SPI0 at 125 kbps
- No network; no ESPHome API; no OTA
- Shared dependency: `canbus_protocol.h` (compile-time only)

**Gateway firmware boundary** (`firmware/gateway.yaml`)

- Input: CAN frames via native TWAI (GPIO15 TX, GPIO16 RX)
- Output: `esphome.canbus_button` events to Home Assistant over WiFi (ESPHome native API)
- Shared dependency: `canbus_protocol.h` (compile-time only)

**Protocol boundary** (`firmware/common/canbus_protocol.h`)

- Defines the wire contract between nodes and gateway
- Frozen after PoC sign-off
- Any change requires recompiling all affected firmware

**HA integration boundary** (network — not a file)

- ESPHome native API over WiFi
- Events fired: `esphome.canbus_button` (room, board, button, event — all strings)
- Heartbeat logging only in PoC; no HA event for heartbeats
- Future: `esphome.canbus_heartbeat`, `esphome.canbus_gateway_canbus_send_output`

**Code generation boundary** (`firmware/nodes.csv` → `generate_nodes.py` → `firmware/nodes/`)

- Input: CSV registry (node_id, room, board, location)
- Output: minimal ESPHome node YAML files (identity + `base_node.yaml` include); shared
  config (SPI/CAN pins, the 8-button set) lives in `base_node.yaml`, not per node
- Invariant: output is fully deterministic from input; running the script twice produces identical output

### Integration Points & Data Flow

```text
Physical button press
  ↓
ESPHome on_multi_click [ firmware/common/button.yaml ]
  ↓ (EVT_CLICK / EVT_DOUBLE_CLICK / etc.)
CAN frame construction [ firmware/common/canbus_protocol.h ]
  can_id(CAT_INPUT, node_id) + button_payload(btn, evt, room, board)
  ↓
MCP2515 SPI0 → CAN bus 125 kbps
  ↓
ESP32-S3 TWAI receiver
  ↓
on_frame if:/condition: guard [ firmware/gateway.yaml ]
  if (x.size() < CAN_FRAME_SIZE) return false; x[0] == PROTO_V1
  decode: room=x[4], board=x[5], button=x[2], event=event_type_str(x[3])
  homeassistant.event: esphome.canbus_button (per-field !lambda)
  ↓
WiFi → Home Assistant native API
  ↓
HA event: esphome.canbus_button { room, board, button, event }
  ↓
HA automation trigger
```

### File Organisation Patterns

**`firmware/nodes.csv` schema:**

```csv
node_id, floor, room, board, location, gpio_list
100, 0, 7, 0, "Hallway entrance", "2,3,4,5"
```

**`firmware/secrets.yaml.example`** (committed template):

```yaml
wifi_ssid: "your_ssid"
wifi_password: "your_password"
ha_api_key: "your_api_key"
```

**ESPHome compile commands (always run from `firmware/` directory):**

```bash
esphome compile nodes/node100.yaml   # compile one node
esphome compile gateway.yaml         # compile gateway
esphome upload nodes/node100.yaml    # flash node via USB
```

## Architecture Validation Results

### Coherence Validation

**Decision Compatibility:** All decisions are mutually compatible.

- ESPHome rp2040 (nodes) and esp-idf (gateway) are independently configured — no shared platform block conflicts.
- The `homeassistant.event:` action with per-field `!lambda` decode is structurally consistent with eliminating globals.
- `canbus_protocol.h` inclusion is compile-time only; no runtime cross-platform issues.
- Node ID ranges (100-399) fit within the 9-bit CAN ID space (0-511).

**Pattern Consistency:** Implementation patterns align with all architectural decisions.
Naming conventions are consistent across C++, ESPHome YAML, and Python. The code-generation
discipline (never edit `nodes/`) is enforced at pattern and structure levels; generated node
files are minimal because shared config (pins, the 8-button set) lives in `common/base_node.yaml`.

**Structure Alignment:** `firmware/` directory and all sub-paths are consistent across
decisions, patterns, and structure sections. Generated vs committed files are clearly
distinguished. Boundaries are non-overlapping.

### Requirements Coverage Validation

**Functional Requirements (9/9 covered):**

| FR | File / Mechanism |
| --- | --- |
| FR-1: Button detection | `firmware/common/button.yaml` |
| FR-2: CAN transmission | `firmware/common/base_node.yaml` + `canbus_protocol.h` |
| FR-3: Heartbeat | `firmware/common/base_node.yaml` |
| FR-4: Protocol header | `firmware/common/canbus_protocol.h` |
| FR-5: Gateway CAN reception | `firmware/gateway.yaml` on_frame pattern |
| FR-6: Gateway HA forwarding | `homeassistant.event:` action in `gateway.yaml` on_frame |
| FR-7: Gateway connectivity | `firmware/secrets.yaml` + WiFi ESPHome config |
| FR-8: Code generation | `firmware/generate_nodes.py` + `firmware/nodes.csv` |
| FR-9: Validation criteria | PoC sign-off criteria (10 combinations + logged artifacts) |

**Non-Functional Requirements (9/9 covered):**
NFR-1 through NFR-9 are addressed through enforcement guidelines, lambda safety
patterns, gateway handler structure, and PoC sign-off criteria. NFR-6 (bus speed)
and NFR-7 (termination) are physical hardware constraints covered by the commissioning
procedure.

### Implementation Readiness Validation

**Decision completeness:** All critical decisions documented. ESPHome version marked
as "pin at first compile" — the verification step is defined.

**Structure completeness:** Full directory tree with every file named. All boundaries
defined with explicit inputs, outputs, and dependencies.

**Pattern completeness:** 8 conflict points identified and addressed. Anti-patterns
listed for code review. Enforcement guidelines are specific and actionable.

### Gap Analysis Results

**Important (non-blocking):**

- `CAN_FRAME_SIZE = 8` constant does not yet exist in `canbus_protocol.h`. Must be added as part of Story 2 (protocol header implementation). Referenced by the lambda safety pattern — agents must add it before writing any on_frame handler.
- PoC bench node IDs should be explicitly assigned: node 100 and node 101 (ground floor range). The `nodes.csv` for the PoC should use these IDs.
- Hardware open questions (OQ-1, OQ-2, OQ-3) must be resolved from physical board documentation before any firmware compiles. These are pre-implementation gates, not architectural gaps.
- Gateway HA event firing uses the documented `homeassistant.event:` YAML action (decision reversed 2026-06-02 from the earlier `api::global_api_server` internal-API approach). No version-specific C++ API lookup required.

**Deferred (accepted):**

- Production gateway board (ESP32-S3-POE-ETH-8DI-8DO) CAN GPIO mapping not validated — explicitly deferred post-PoC.
- Room name translation (integer → human-readable string) — deferred to HA templates.
- Node health dashboard and aliveness alerting — deferred post-PoC.

### Architecture Completeness Checklist

#### Requirements Analysis

- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed
- [x] Technical constraints identified
- [x] Cross-cutting concerns mapped

#### Architectural Decisions

- [x] Critical decisions documented with versions
- [x] Technology stack fully specified
- [x] Integration patterns defined
- [x] Performance considerations addressed

#### Implementation Patterns

- [x] Naming conventions established
- [x] Structure patterns defined
- [x] Communication patterns specified
- [x] Process patterns documented

#### Project Structure

- [x] Complete directory structure defined
- [x] Component boundaries established
- [x] Integration points mapped
- [x] Requirements to structure mapping complete

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION

**Confidence Level:** High

**Key Strengths:**

- Protocol freeze risk is explicitly named and managed — the architecture treats the CAN wire format as a hardware interface, not software.
- The "no globals for staging" decision simplifies the gateway significantly and removes a class of subtle ESPHome bugs.
- Code generation pipeline is clearly scoped: `nodes.csv` is hardware truth, `nodes/` is output.
- Enforcement guidelines are specific enough for code review use.

**Areas for Future Enhancement:**

- ESPHome version management: once pinned, a process for evaluating upgrades (specifically re-validating the direct API call approach) should be established.
- Production gateway board validation is the next major architecture gate after PoC.
- Node health monitoring (heartbeat → HA event → aliveness dashboard) is the natural next feature after PoC sign-off.
- CAN bus topology sketch (cable lengths, ground continuity across floors) should precede production installation — the topology *method* is now decided (ADR-0005: segmented multi-bus with software bridges); the sketch sets the segment/bridge count (ADR-0005 open item 1).

### Implementation Handoff

**AI Agent Guidelines:**

- Read `firmware/common/canbus_protocol.h` before writing any CAN-related lambda
- Read this document section "Implementation Patterns & Consistency Rules" before starting any story
- Check `firmware/nodes.csv` before assigning any node ID
- Compile with `esphome compile` before marking any story done

**First Implementation Story:** Directory restructure — move `docs/esphome_canbus/` contents to `firmware/`, update all relative paths in YAML includes, verify `esphome compile` still passes on at least one node config.
