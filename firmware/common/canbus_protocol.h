#pragma once
#include <vector>
#include <string>
#include <cstdint>
#include <cstddef>

// =============================================================================
// CAN Bus Smart Home Protocol v1 — Extended IDs, location-as-address (ADR-0001)
// =============================================================================
//
// 29-bit Extended CAN ID. Identity + classification live in the ID; the payload
// carries only values/parameters. The flat node_id is gone — a node's address
// *is* its (room, board). (room, board) MUST be globally unique; a duplicate is a
// physical address collision (two boards answering one ID) — enforced in
// generate_nodes.py.
//
//   Common high fields (all categories):
//
//   Bit: 28 27 26 │ 25 24 23 22 21 20 19 18 │ 17 16 15 14 13 12 11 10 │ 9 .......... 0
//        C  C  C  │ R  R  R  R  R  R  R  R  │ B  B  B  B  B  B  B  B  │ per-category (10)
//        cat:3    │ room:8  (shift 18)       │ board:8 (shift 10)       │ low 10 bits
//
//   Per-category use of the low 10 bits [9:0]:
//     INPUT  (1):  button:4 [9:6]  event:4 [5:2]  rsvd:2 [1:0]
//     OUTPUT (2):  gateway_id:4 [9:6]  subtype:5 [5:1]  rsvd:1 [0]
//     STATUS (3):  rsvd:10 [9:0] = 0          (values stay in payload)
//     SYSTEM (0):  reserved — shape defined later (gateway heartbeat); not built yet
//
// Payloads after the move (identity/event left the payload):
//   INPUT  (button):    [PROTO_V1]                                  — 1 byte (version gate)
//   STATUS (heartbeat): [PROTO_V1, MSG_HEARTBEAT, errors, up_lo, up_hi]   — 5 bytes
//   OUTPUT (command):   [PROTO_V1, params…]  — command type is the ID subtype
//     config write:     [PROTO_V1, key, val_hi, val_lo]
//
// gateway_id is a *source* tag on OUTPUT only (POC = 0). Nodes accept commands for
// their (room, board) regardless of gateway_id — see the OUTPUT RX filter mask below.
// =============================================================================

// --------------- Protocol version ---------------
// Versioning policy: until the project is declared LIVE, PROTO_V1 stays 0x01 and breaking
// changes are absorbed in place (every node is reflashed in lock-step with the gateway —
// there is no fielded firmware to stay compatible with). Going live is Alberto's explicit
// call; only after that does any breaking change require a version bump.
inline constexpr uint8_t PROTO_V1 = 0x01;

// Per-frame minimum payload lengths (DLC). Identity moved into the ID, so frames are
// short; handlers validate against the relevant minimum rather than a fixed 8 bytes.
inline constexpr std::size_t INPUT_PAYLOAD_MIN = 1;     // [ver]
inline constexpr std::size_t STATUS_PAYLOAD_MIN = 5;    // [ver, type, errors, up_lo, up_hi]
inline constexpr std::size_t CONFIG_PAYLOAD_MIN = 4;    // [ver, key, val_hi, val_lo]

// --------------- Categories (ID bits 28:26) ---------------
inline constexpr uint8_t CAT_SYSTEM = 0; // Emergency, errors, gateway heartbeat (highest priority)
inline constexpr uint8_t CAT_INPUT = 1;  // Button events            node → gateway
inline constexpr uint8_t CAT_OUTPUT = 2; // LED/relay commands       gateway → node
inline constexpr uint8_t CAT_STATUS = 3; // Heartbeat, health        node → gateway

// --------------- ID field shifts / masks ---------------
inline constexpr uint8_t CAT_SHIFT = 26;
inline constexpr uint8_t ROOM_SHIFT = 18;
inline constexpr uint8_t BOARD_SHIFT = 10;
// INPUT low bits
inline constexpr uint8_t BUTTON_SHIFT = 6; // 4 bits
inline constexpr uint8_t EVENT_SHIFT = 2;  // 4 bits
// OUTPUT low bits
inline constexpr uint8_t GATEWAY_SHIFT = 6; // 4 bits
inline constexpr uint8_t SUBTYPE_SHIFT = 1; // 5 bits

// Match category bits only (gateway INPUT/STATUS acceptance filters).
inline constexpr uint32_t CAN_MASK_CATEGORY = 0x1C000000u; // bits 28:26
// Match category + room + board, ignoring the low 10 bits (node OUTPUT RX filter — a node
// accepts a command for its location regardless of gateway_id / subtype).
inline constexpr uint32_t CAN_MASK_OUTPUT_ADDR = 0x1FFFFC00u; // bits 28:10

// --------------- OUTPUT command subtypes (ID subtype field) ---------------
inline constexpr uint8_t SUBTYPE_OUTPUT_CMD = 0x01;   // generic LED/relay command
inline constexpr uint8_t SUBTYPE_CONFIG_WRITE = 0x02; // write a config parameter

// --------------- STATUS message types (payload byte 1) ---------------
inline constexpr uint8_t MSG_HEARTBEAT = 0x01;

// --------------- Button event types (ID event field, 4 bits) ---------------
inline constexpr uint8_t EVT_CLICK = 0x01;
inline constexpr uint8_t EVT_DOUBLE_CLICK = 0x02;
inline constexpr uint8_t EVT_TRIPLE_CLICK = 0x03;
inline constexpr uint8_t EVT_LONG_PRESS = 0x04;
inline constexpr uint8_t EVT_EXTRA_LONG_PRESS = 0x05;

// Backward-compatible aliases for older YAML packages that still use the pre-PRD names.
inline constexpr uint8_t EVT_DOUBLE = EVT_DOUBLE_CLICK;
inline constexpr uint8_t EVT_TRIPLE = EVT_TRIPLE_CLICK;
inline constexpr uint8_t EVT_LONG = EVT_LONG_PRESS;
inline constexpr uint8_t EVT_EXTRA_LONG = EVT_EXTRA_LONG_PRESS;

// --------------- Error flags (heartbeat) ---------------
inline constexpr uint8_t ERR_NONE = 0x00;
inline constexpr uint8_t ERR_CAN_TX_FAIL = 0x01;
inline constexpr uint8_t ERR_CAN_BUS_OFF = 0x02;

// =============================================================================
// CAN ID encoders — all return a 29-bit Extended ID (send with use_extended_id = true)
// =============================================================================

// Shared high field: [category][room][board].
inline uint32_t can_addr(uint8_t category, uint8_t room, uint8_t board)
{
  return (static_cast<uint32_t>(category & 0x07) << CAT_SHIFT) |
         (static_cast<uint32_t>(room) << ROOM_SHIFT) |
         (static_cast<uint32_t>(board) << BOARD_SHIFT);
}

// INPUT (node → gateway): button + event ride the ID.
inline uint32_t can_input_id(uint8_t room, uint8_t board, uint8_t button, uint8_t event)
{
  return can_addr(CAT_INPUT, room, board) |
         (static_cast<uint32_t>(button & 0x0F) << BUTTON_SHIFT) |
         (static_cast<uint32_t>(event & 0x0F) << EVENT_SHIFT);
}

// STATUS (node → gateway): heartbeat. Low 10 bits reserved (0).
inline uint32_t can_status_id(uint8_t room, uint8_t board)
{
  return can_addr(CAT_STATUS, room, board);
}

// OUTPUT (gateway → node): gateway_id source tag + command subtype.
inline uint32_t can_output_id(uint8_t room, uint8_t board, uint8_t gateway_id, uint8_t subtype)
{
  return can_addr(CAT_OUTPUT, room, board) |
         (static_cast<uint32_t>(gateway_id & 0x0F) << GATEWAY_SHIFT) |
         (static_cast<uint32_t>(subtype & 0x1F) << SUBTYPE_SHIFT);
}

// OUTPUT RX acceptance-filter match value for a node (use with CAN_MASK_OUTPUT_ADDR).
inline uint32_t can_output_filter(uint8_t room, uint8_t board)
{
  return can_addr(CAT_OUTPUT, room, board);
}

// =============================================================================
// CAN ID decoders — for gateway / node use (read identity from the frame's can_id)
// =============================================================================

inline uint8_t id_category(uint32_t id) { return (id >> CAT_SHIFT) & 0x07; }
inline uint8_t id_room(uint32_t id) { return (id >> ROOM_SHIFT) & 0xFF; }
inline uint8_t id_board(uint32_t id) { return (id >> BOARD_SHIFT) & 0xFF; }
// INPUT
inline uint8_t id_button(uint32_t id) { return (id >> BUTTON_SHIFT) & 0x0F; }
inline uint8_t id_event(uint32_t id) { return (id >> EVENT_SHIFT) & 0x0F; }
// OUTPUT
inline uint8_t id_gateway(uint32_t id) { return (id >> GATEWAY_SHIFT) & 0x0F; }
inline uint8_t id_subtype(uint32_t id) { return (id >> SUBTYPE_SHIFT) & 0x1F; }

// =============================================================================
// Payload builders
// =============================================================================

// INPUT (button): identity + event are in the ID; payload keeps only the version gate.
inline std::vector<uint8_t> input_payload() { return {PROTO_V1}; }

// STATUS (heartbeat): [ver, type, errors, uptime_lo, uptime_hi].
// uptime_hours is a little-endian uint16; 0xFFFF means "at least 65535 h".
inline std::vector<uint8_t> heartbeat_payload(uint16_t uptime_hours, uint8_t error_flags)
{
  return {PROTO_V1, MSG_HEARTBEAT, error_flags,
          (uint8_t) (uptime_hours & 0xFF), (uint8_t) ((uptime_hours >> 8) & 0xFF)};
}

// =============================================================================
// Payload decoders — for gateway use
// =============================================================================

inline uint8_t payload_version(const std::vector<uint8_t> &d) { return d.size() > 0 ? d[0] : 0; }

// Heartbeat content — [ver, type, errors, uptime_lo, uptime_hi].
inline uint8_t payload_hb_type(const std::vector<uint8_t> &d) { return d.size() > 1 ? d[1] : 0; }
inline uint8_t payload_errors(const std::vector<uint8_t> &d) { return d.size() > 2 ? d[2] : 0; }
inline uint16_t payload_uptime16(const std::vector<uint8_t> &d)
{
  if (d.size() < STATUS_PAYLOAD_MIN) return 0;
  return (uint16_t) d[3] | ((uint16_t) d[4] << 8);
}

// Event type to string (for HA events)
inline std::string event_type_str(uint8_t event_type)
{
  switch (event_type)
  {
  case EVT_CLICK:
    return "click";
  case EVT_DOUBLE_CLICK:
    return "double_click";
  case EVT_TRIPLE_CLICK:
    return "triple_click";
  case EVT_LONG_PRESS:
    return "long_press";
  case EVT_EXTRA_LONG_PRESS:
    return "extra_long_press";
  default:
    return "unknown";
  }
}
