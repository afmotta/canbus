#pragma once
#include <vector>
#include <string>
#include <cstdint>
#include <cstddef>

// =============================================================================
// CAN Bus Smart Home Protocol v1 — flat node_id, 29-bit Extended IDs (ADR-0007)
// =============================================================================
//
// 29-bit Extended CAN ID, uniform across all categories:
//
//   Bit: 28 27 26 25 │ 24 .............. 12 │ 11 ............. 0
//        C  C  C  C   │ N  N  ........  N     │ r  r  ........  r
//
//   C = category (4 bits, 0-15)   — message class + arbitration priority (lower = higher)
//   N = node_id  (13 bits, 0-8191) — flat, meaningless, assigned at flash time
//   r = reserved (12 bits)         — future per-category low fields; MUST be 0 for now
//
// A node's identity is its flat node_id. (room, board, behaviour) live in a central
// node_id -> {...} map on the controller/HA (ADR-0007) — never on the node. The CAN ID
// carries only the message class + node_id; ALL message content lives in the payload.
//
// Node -> controller payloads (uniform [version][type] header, then content):
//   Byte 0:  protocol version
//   Byte 1:  message type
//   Byte 2+: message-specific content
//     INPUT  (button):    [ver, MSG_BUTTON_EVENT, button_index, event_type]
//     STATUS (heartbeat): [ver, MSG_HEARTBEAT, error_flags, uptime_lo, uptime_hi]  (uint16 LE)
//
// Controller -> node (OUTPUT) payloads carry command/config params: [ver, subtype, ...];
// the node_id in the ID addresses the target (defined by the controller in a later slice).
//
// Scope of this header (PR-A): the ID framework + the node TX path (button + heartbeat).
// Sensors (CAT_SENSOR, ADR-0006) and the OUTPUT command set land in later slices; the
// reserved low 12 bits stay 0 until a consumer needs to hardware-filter on them.
// =============================================================================

// --------------- Protocol version ---------------
// Versioning policy: until the project is declared LIVE, PROTO_V1 stays 0x01 and breaking
// changes are absorbed in place (every node is reflashed in lock-step — there is no fielded
// firmware to stay compatible with). Going live is Alberto's call; only after that does a
// breaking change require a version bump.
inline constexpr uint8_t PROTO_V1 = 0x01;

// Frame sizing. Content moved into the ID-addressed/short payloads, so frames are <= 8 bytes
// and variable-length; receive lambdas guard against the relevant per-message minimum rather
// than a fixed 8 (named constants, never inlined — NFR-2).
inline constexpr std::size_t CAN_FRAME_MAX = 8;
inline constexpr std::size_t HEADER_MIN = 2;             // [ver, type]
inline constexpr std::size_t BUTTON_PAYLOAD_MIN = 4;     // [ver, type, button, event]
inline constexpr std::size_t HEARTBEAT_PAYLOAD_MIN = 5;  // [ver, type, errors, up_lo, up_hi]

// --------------- Categories (ID bits 28:25, 4 bits) ---------------
// Lower value = higher CAN arbitration priority. 0-3 retained from v1.
inline constexpr uint8_t CAT_SYSTEM = 0;   // emergency, errors, controller liveness (highest)
inline constexpr uint8_t CAT_INPUT = 1;    // button events             node -> controller
inline constexpr uint8_t CAT_OUTPUT = 2;   // commands / management     controller -> node
inline constexpr uint8_t CAT_STATUS = 3;   // heartbeat, health         node -> controller
inline constexpr uint8_t CAT_SENSOR = 4;   // environmental (ADR-0006)  node -> controller (low priority)
// Values 5-14 are reserved for future message classes (e.g. CONFIG, DISCOVERY, BOOTLOADER);
// assign them when those slices are designed.
inline constexpr uint8_t CAT_EXTENDED = 15; // escape: real class is a subtype byte in the payload

// --------------- ID field layout ---------------
inline constexpr uint8_t CAT_SHIFT = 25;
inline constexpr uint8_t NODE_SHIFT = 12;
inline constexpr uint32_t CAT_FIELD_MASK = 0x0Fu;    // 4 bits
inline constexpr uint32_t NODE_FIELD_MASK = 0x1FFFu; // 13 bits

// Match category bits only (controller/gateway category-mask acceptance filter).
inline constexpr uint32_t CAN_MASK_CATEGORY = CAT_FIELD_MASK << CAT_SHIFT;  // 0x1E000000
// Match category + node_id (a node's RX filter for OUTPUT frames addressed to it; used later).
inline constexpr uint32_t CAN_MASK_ADDR =
    (CAT_FIELD_MASK << CAT_SHIFT) | (NODE_FIELD_MASK << NODE_SHIFT);

// --------------- Message types (payload byte 1) ---------------
inline constexpr uint8_t MSG_BUTTON_EVENT = 0x01;
inline constexpr uint8_t MSG_HEARTBEAT = 0x01;
inline constexpr uint8_t MSG_CONFIG_WRITE = 0x02;
inline constexpr uint8_t MSG_CONFIG_ACK = 0x03;

// --------------- Button event types (payload) ---------------
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
// CAN ID helpers — 29-bit Extended IDs (send with use_extended_id = true)
// =============================================================================

inline uint32_t can_id(uint8_t category, uint16_t node_id)
{
  return ((static_cast<uint32_t>(category) & CAT_FIELD_MASK) << CAT_SHIFT) |
         ((static_cast<uint32_t>(node_id) & NODE_FIELD_MASK) << NODE_SHIFT);
}

inline uint8_t can_id_category(uint32_t id) { return (id >> CAT_SHIFT) & CAT_FIELD_MASK; }
inline uint16_t can_id_node(uint32_t id) { return (id >> NODE_SHIFT) & NODE_FIELD_MASK; }

// =============================================================================
// Payload builders — identity is the node_id in the ID; content is in the payload
// =============================================================================

// Button event: [ver, type, button_index, event_type].
inline std::vector<uint8_t> button_payload(uint8_t button_index, uint8_t event_type)
{
  return {PROTO_V1, MSG_BUTTON_EVENT, button_index, event_type};
}

// Heartbeat: [ver, type, error_flags, uptime_lo, uptime_hi].
// uptime_hours is a little-endian uint16 (bytes 3-4); 0xFFFF means "at least 65535 h".
inline std::vector<uint8_t> heartbeat_payload(uint16_t uptime_hours, uint8_t error_flags)
{
  return {PROTO_V1, MSG_HEARTBEAT, error_flags,
          (uint8_t) (uptime_hours & 0xFF), (uint8_t) ((uptime_hours >> 8) & 0xFF)};
}

// =============================================================================
// Payload decoders — for controller/gateway use
// =============================================================================

inline uint8_t payload_version(const std::vector<uint8_t> &d) { return d.size() > 0 ? d[0] : 0; }
inline uint8_t payload_type(const std::vector<uint8_t> &d) { return d.size() > 1 ? d[1] : 0; }

// Button-event content (after the [ver, type] header).
inline uint8_t payload_button_index(const std::vector<uint8_t> &d) { return d.size() > 2 ? d[2] : 0; }
inline uint8_t payload_event_type(const std::vector<uint8_t> &d) { return d.size() > 3 ? d[3] : 0; }

// Heartbeat content — errors at byte 2, uptime a little-endian uint16 at bytes 3-4.
inline uint8_t payload_errors(const std::vector<uint8_t> &d) { return d.size() > 2 ? d[2] : 0; }
inline uint16_t payload_uptime16(const std::vector<uint8_t> &d)
{
  if (d.size() < HEARTBEAT_PAYLOAD_MIN) return 0;
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
