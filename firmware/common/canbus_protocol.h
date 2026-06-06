#pragma once
#include <vector>
#include <string>
#include <cstdint>
#include <cstddef>

// =============================================================================
// CAN Bus Smart Home Protocol v1
// =============================================================================
//
// CAN ID structure (standard 11-bit):
//
//   Bit:  10  9 │ 8  7  6  5  4  3  2  1  0
//         C   C │ N  N  N  N  N  N  N  N  N
//
//   C = Category (2 bits, 0-3)  — bus arbitration priority (lower = higher)
//   N = Node ID  (9 bits, 0-511) — flat, sequential, assigned in registry
//
// Capacity: 512 unique nodes
//
// All semantic meaning (room, board, button, event) lives in the payload.
// The CAN ID only provides uniqueness for arbitration and category filtering.
//
// Node → gateway payload (8 bytes) — uniform [version][type] header, then identity:
//   Byte 0:   Protocol version
//   Byte 1:   Message type
//   Byte 2:   Room ID   (0-255)  — sender identity, same offset for every node→gateway frame
//   Byte 3:   Board ID  (0-255)  — sender identity, same offset for every node→gateway frame
//   Byte 4-6: Message-specific content (trails identity, contiguous with the reserved tail)
//   Byte 7:   Reserved
//
//   Button event content: Byte 4 = button index, Byte 5 = event type      (6-7 reserved)
//   Heartbeat content:    Byte 4 = error flags,  Byte 5-6 = uptime hours (uint16 LE), 7 reserved
//
// Gateway → node payload (8 bytes) carries command params, not room/board — the CAN ID
// already addresses the target node:  [version, subtype/type, p1, p2, ...].
// =============================================================================

// --------------- Protocol version ---------------
// Versioning policy: until the project is declared LIVE, PROTO_V1 stays 0x01 and breaking
// payload changes are absorbed in place (every node is reflashed in lock-step with the
// gateway — there is no fielded firmware to stay compatible with). Going live is Alberto's
// explicit call; only after that does any breaking payload change require a version bump.
inline constexpr uint8_t PROTO_V1 = 0x01;
// size_t so comparisons against std::vector::size() are exact (no implicit promotion).
inline constexpr std::size_t CAN_FRAME_SIZE = 8;

// --------------- Categories (bits 10:9) ---------------
inline constexpr uint8_t CAT_SYSTEM = 0; // Emergency, errors       (highest priority)
inline constexpr uint8_t CAT_INPUT = 1;  // Button events            node → gateway
inline constexpr uint8_t CAT_OUTPUT = 2; // LED/relay commands       gateway → node
inline constexpr uint8_t CAT_STATUS = 3; // Heartbeat, health        node → gateway

// CAN ID mask: match category bits only (bits 10:9)
inline constexpr uint32_t CAN_MASK_CATEGORY = 0x600;

// --------------- Message types (payload byte 1) ---------------
inline constexpr uint8_t MSG_BUTTON_EVENT = 0x01;
inline constexpr uint8_t MSG_HEARTBEAT = 0x01;
inline constexpr uint8_t MSG_CONFIG_WRITE = 0x02;
inline constexpr uint8_t MSG_CONFIG_ACK = 0x03;

// --------------- Button event types (payload byte 3) ---------------
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

// --------------- Error flags (heartbeat byte 4) ---------------
inline constexpr uint8_t ERR_NONE = 0x00;
inline constexpr uint8_t ERR_CAN_TX_FAIL = 0x01;
inline constexpr uint8_t ERR_CAN_BUS_OFF = 0x02;

// =============================================================================
// CAN ID helpers
// =============================================================================

inline uint32_t can_id(uint8_t category, uint16_t node_id)
{
  return (static_cast<uint32_t>(category & 0x03) << 9) | (node_id & 0x1FF);
}

inline uint8_t can_id_category(uint32_t id) { return (id >> 9) & 0x03; }
inline uint16_t can_id_node(uint32_t id) { return id & 0x1FF; }

// =============================================================================
// Payload builders — all return 8-byte vectors
// Room and board identify the sender; node_id is only in the CAN header.
// =============================================================================

// Button event: [ver, type, room, board, button, event, 0, 0]
inline std::vector<uint8_t> button_payload(uint8_t button_index, uint8_t event_type,
                                           uint8_t room_id, uint8_t board_id)
{
  return {PROTO_V1, MSG_BUTTON_EVENT, room_id, board_id, button_index, event_type, 0x00, 0x00};
}

// Heartbeat: [ver, type, room, board, errors, uptime_lo, uptime_hi, 0]
// uptime_hours is a little-endian uint16 (bytes 5-6); 0xFFFF means "at least 65535 h".
inline std::vector<uint8_t> heartbeat_payload(uint16_t uptime_hours,
                                              uint8_t error_flags, uint8_t room_id, uint8_t board_id)
{
  return {PROTO_V1, MSG_HEARTBEAT, room_id, board_id, error_flags,
          (uint8_t) (uptime_hours & 0xFF), (uint8_t) ((uptime_hours >> 8) & 0xFF), 0x00};
}

// =============================================================================
// Payload decoders — for gateway use
// =============================================================================

inline uint8_t payload_version(const std::vector<uint8_t> &d) { return d.size() > 0 ? d[0] : 0; }
inline uint8_t payload_type(const std::vector<uint8_t> &d) { return d.size() > 1 ? d[1] : 0; }

// Sender identity — same offset for every node→gateway frame (button + heartbeat).
inline uint8_t payload_room(const std::vector<uint8_t> &d) { return d.size() > 2 ? d[2] : 0; }
inline uint8_t payload_board(const std::vector<uint8_t> &d) { return d.size() > 3 ? d[3] : 0; }

// Button-event content
inline uint8_t payload_button_index(const std::vector<uint8_t> &d) { return d.size() > 4 ? d[4] : 0; }
inline uint8_t payload_event_type(const std::vector<uint8_t> &d) { return d.size() > 5 ? d[5] : 0; }

// Heartbeat content — uptime is a little-endian uint16 spanning bytes 5-6.
inline uint8_t payload_errors(const std::vector<uint8_t> &d) { return d.size() > 4 ? d[4] : 0; }
inline uint16_t payload_uptime16(const std::vector<uint8_t> &d)
{
  if (d.size() < 7) return 0;
  return (uint16_t) d[5] | ((uint16_t) d[6] << 8);
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
