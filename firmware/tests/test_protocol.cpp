// Standalone native round-trip test for canbus_protocol.h (no ESPHome required).
// Build & run:  g++ -std=c++17 -Wall -Wextra firmware/tests/test_protocol.cpp -o /tmp/proto && /tmp/proto
//
// Validates the ADR-0007 Extended-ID layout [category:4][node_id:13][reserved:12] and the
// node TX payloads (button + heartbeat). Pure logic; CI/desktop runnable.

#include "../protocol/canbus_protocol.h"
#include <cassert>
#include <cstdio>

int main()
{
  // --- ID encode/decode round-trip ---
  for (uint16_t node : {0u, 1u, 100u, 4095u, 8191u}) {
    for (uint8_t cat : {CAT_SYSTEM, CAT_INPUT, CAT_OUTPUT, CAT_STATUS, CAT_SENSOR, CAT_EXTENDED}) {
      uint32_t id = can_id(cat, node);
      assert(id < (1u << 29));                 // fits in 29-bit Extended ID
      assert((id & 0x0FFFu) == 0);             // low 12 bits reserved == 0
      assert(can_id_category(id) == cat);
      assert(can_id_node(id) == node);
    }
  }

  // --- field placement & masks ---
  assert(CAT_SHIFT == 25 && NODE_SHIFT == 12);
  assert(CAN_MASK_CATEGORY == 0x1E000000u);
  assert(CAN_MASK_ADDR == (0x1E000000u | (0x1FFFu << 12)));
  // node_id wraps at 13 bits; category at 4 bits
  assert(can_id_node(can_id(CAT_INPUT, 8192)) == 0);     // 8192 & 0x1FFF == 0
  assert(can_id_category(can_id(16, 1)) == 0);           // 16 & 0xF == 0
  assert(CAT_SENSOR == 4 && CAT_EXTENDED == 15);

  // --- button payload ---
  auto bp = button_payload(3, EVT_DOUBLE_CLICK);
  assert(bp.size() >= BUTTON_PAYLOAD_MIN);
  assert(payload_version(bp) == PROTO_V1 && payload_type(bp) == MSG_BUTTON_EVENT);
  assert(payload_button_index(bp) == 3 && payload_event_type(bp) == EVT_DOUBLE_CLICK);

  // --- heartbeat payload (uptime uint16 LE, errors at byte 2) ---
  auto hb = heartbeat_payload(1234, ERR_CAN_TX_FAIL);
  assert(hb.size() >= HEARTBEAT_PAYLOAD_MIN);
  assert(payload_version(hb) == PROTO_V1 && payload_type(hb) == MSG_HEARTBEAT);
  assert(payload_errors(hb) == ERR_CAN_TX_FAIL);
  assert(payload_uptime16(hb) == 1234);
  assert(payload_uptime16(heartbeat_payload(0xFFFF, ERR_NONE)) == 0xFFFF);

  // --- sensor payload (CAT_SENSOR, ADR-0006): status + uint16 meas_type + int32 value ---
  auto sp = sensor_payload(SENSOR_SHT45_TEMP, 2143 /* 21.43 C */);
  assert(sp.size() == SENSOR_PAYLOAD_MIN);
  assert(payload_version(sp) == PROTO_V1 && payload_sensor_status(sp) == SENSOR_STATUS_OK);
  assert(payload_measurement_type(sp) == SENSOR_SHT45_TEMP);
  assert(payload_sensor_value32(sp) == 2143);
  // negative temperature survives the int32 round-trip
  assert(payload_sensor_value32(sensor_payload(SENSOR_SEN66_TEMP, -512)) == -512);
  // a non-OK status carries through
  auto sw = sensor_payload(SENSOR_SEN66_CO2, 0, SENSOR_STATUS_WARMING_UP);
  assert(payload_sensor_status(sw) == SENSOR_STATUS_WARMING_UP &&
         payload_measurement_type(sw) == SENSOR_SEN66_CO2);
  // CAT_SENSOR frame id is just can_id(CAT_SENSOR, node_id)
  assert(can_id_category(can_id(CAT_SENSOR, 100)) == CAT_SENSOR);

  // --- short-frame guards return 0, never crash ---
  std::vector<uint8_t> empty;
  assert(payload_version(empty) == 0 && payload_uptime16(empty) == 0);
  assert(payload_measurement_type(empty) == SENSOR_MEAS_INVALID && payload_sensor_value32(empty) == 0);

  // --- event strings ---
  assert(event_type_str(EVT_CLICK) == "click");
  assert(event_type_str(EVT_EXTRA_LONG_PRESS) == "extra_long_press");
  assert(event_type_str(0xFF) == "unknown");

  std::printf("ALL PROTOCOL SELF-CHECKS PASSED\n");
  return 0;
}
