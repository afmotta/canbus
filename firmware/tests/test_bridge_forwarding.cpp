// Standalone native test for bridge_forwarding.h (no ESPHome required).
// Build & run:  g++ -std=c++17 -Wall -Wextra firmware/tests/test_bridge_forwarding.cpp -o /tmp/bridge && /tmp/bridge
//
// Covers the ADR-0005 store-and-forward queue: FIFO order and payload fidelity,
// the oversize/overflow drop rules (drop-newest, counted), the paced drain cap,
// and the latched heartbeat overflow flag.

#include "../protocol/bridge_forwarding.h"
#include <cassert>
#include <cstdio>

int main()
{
  // --- enqueue/drain round-trip preserves id, flag, length, bytes, order ---
  std::vector<BridgeFrame> q;
  BridgeStats s{};
  assert(bridge_enqueue(q, s, can_id(CAT_INPUT, 100), true, button_payload(3, EVT_CLICK)));
  assert(bridge_enqueue(q, s, can_id(CAT_STATUS, 101), true, heartbeat_payload(7, ERR_NONE)));
  assert(q.size() == 2 && s.enqueued == 2);
  auto out = bridge_drain(q, s);                  // default cap = BRIDGE_DRAIN_MAX = 2
  assert(out.size() == 2 && q.empty() && s.forwarded == 2);
  assert(out[0].can_id == can_id(CAT_INPUT, 100) && out[0].extended);
  assert(out[0].len == 4 && out[0].data[2] == 3 && out[0].data[3] == EVT_CLICK);
  assert(out[1].can_id == can_id(CAT_STATUS, 101));
  assert(out[1].len == 5 && out[1].data[3] == 7 && out[1].data[4] == 0);  // uptime LE

  // --- drain of an empty queue is a no-op ---
  assert(bridge_drain(q, s).empty() && s.forwarded == 2);

  // --- oversize frame rejected, queue untouched ---
  std::vector<uint8_t> nine(9, 0xAA);
  assert(!bridge_enqueue(q, s, 0x123, true, nine));
  assert(q.empty() && s.dropped_oversize == 1 && s.enqueued == 2);
  std::vector<uint8_t> eight(8, 0xBB);            // exactly CAN_FRAME_MAX is fine
  assert(bridge_enqueue(q, s, 0x123, true, eight));
  assert(q.size() == 1 && q[0].len == 8 && q[0].data[7] == 0xBB);
  q.clear();

  // --- overflow drops the NEW frame; queued frames and their order survive ---
  std::vector<BridgeFrame> full;
  BridgeStats fs{};
  for (uint32_t i = 0; i < BRIDGE_QUEUE_MAX; ++i)
    assert(bridge_enqueue(full, fs, 1000 + i, true, {PROTO_V1}));
  assert(full.size() == BRIDGE_QUEUE_MAX);
  assert(!bridge_enqueue(full, fs, 9999, true, {PROTO_V1}));
  assert(full.size() == BRIDGE_QUEUE_MAX && fs.dropped_overflow == 1);
  assert(full.front().can_id == 1000 && full.back().can_id == 1000 + BRIDGE_QUEUE_MAX - 1);

  // --- drain cap: at most max_frames per call, oldest first, FIFO across calls ---
  auto batch = bridge_drain(full, fs);
  assert(batch.size() == BRIDGE_DRAIN_MAX);
  assert(batch[0].can_id == 1000 && batch[1].can_id == 1001);
  batch = bridge_drain(full, fs, 3);              // explicit cap
  assert(batch.size() == 3 && batch[0].can_id == 1002 && batch[2].can_id == 1004);
  assert(full.size() == BRIDGE_QUEUE_MAX - 5);
  assert(fs.forwarded == 5);

  // --- heartbeat flag: clean stats -> ERR_NONE; any drop in either direction latches ---
  BridgeStats clean{};
  assert(bridge_error_flags(clean, clean) == ERR_NONE);
  assert(bridge_error_flags(fs, clean) == ERR_BRIDGE_QUEUE_OVERFLOW);   // overflow side
  assert(bridge_error_flags(clean, s) == ERR_BRIDGE_QUEUE_OVERFLOW);    // oversize side
  // cumulative counters never reset -> the flag is sticky by construction
  assert(bridge_error_flags(fs, s) == ERR_BRIDGE_QUEUE_OVERFLOW);

  // --- static stores exist and are distinct per direction ---
  bridge_queue_to_backbone().clear();
  bridge_queue_to_zone().clear();
  assert(bridge_enqueue(bridge_queue_to_backbone(), bridge_stats_to_backbone(),
                        can_id(CAT_INPUT, 100), true, button_payload(0, EVT_CLICK)));
  assert(bridge_queue_to_backbone().size() == 1 && bridge_queue_to_zone().empty());

  printf("test_bridge_forwarding: all assertions passed\n");
  return 0;
}
