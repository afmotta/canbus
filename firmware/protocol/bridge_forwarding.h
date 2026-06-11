#pragma once
#include <cstdint>
#include <cstddef>
#include <vector>

#include "canbus_protocol.h"

// =============================================================================
// Segment-bridge store-and-forward queues — ADR-0005 (segmented multi-bus)
// =============================================================================
//
// A bridge joins two CAN segments: a backbone (controller) side and a zone
// (secondary) side. Forwarding is forward-all both ways (ADR-0005 open item 3:
// the controller needs all node traffic, management must reach every segment);
// the loop-free tree topology and the controllers' no-self-reception (TWAI and
// MCP2515 alike in normal mode) mean a forwarded frame can never echo back
// through the same bridge.
//
// Frames are queued on receive and drained on a fixed tick, at most
// BRIDGE_DRAIN_MAX per direction per tick. The pacing matters more than the
// buffering: on the LilyGO T-2CAN the zone side is an MCP2515 with only 3 TX
// buffers, and a 125 kbps frame takes ~1 ms on the wire, so blasting a
// received burst straight into send_data() would overrun the TX side. The
// queue absorbs the burst; the drain cap meters it out at a rate the weaker
// transmitter can sustain (applied to both directions for symmetry).
//
// Pure logic only — no ESPHome includes — so the queue/pacing machinery is
// natively testable (see tests/test_bridge_forwarding.cpp).
// =============================================================================

// A received frame held for forwarding to the other segment.
struct BridgeFrame
{
  uint32_t can_id;
  bool extended;
  uint8_t len;
  uint8_t data[CAN_FRAME_MAX];
};

// Cumulative per-direction counters. dropped_* never reset, so any nonzero
// value latches the heartbeat overflow flag until reboot (conservative: a
// bridge that ever dropped a frame stays visibly degraded, ADR-0005 fail-safe
// posture).
struct BridgeStats
{
  uint32_t enqueued;
  uint32_t forwarded;
  uint32_t dropped_overflow;
  uint32_t dropped_oversize;
};

// Queue depth per direction: ~32 ms of a 100%-utilized 125 kbps segment
// (extended data frame ~1 ms on the wire) — far beyond any home-scale burst.
// Past this the segment itself is saturated and dropping is the honest outcome.
inline constexpr std::size_t BRIDGE_QUEUE_MAX = 32;
// Frames drained per direction per tick. At a 10 ms tick this paces TX to
// 200 frames/s per direction — under the 3 TX buffers and ~1 ms/frame the
// MCP2515 (the weaker TX side) can sustain, and far above expected load.
inline constexpr std::size_t BRIDGE_DRAIN_MAX = 2;

// Queue a received frame for the other segment. Oversize frames (> 8 data
// bytes; impossible from a conformant CAN controller) are rejected. On a full
// queue the NEW frame is dropped (drop-newest): the already-queued frames are
// older and closer to delivery, and never re-ordering the FIFO keeps event
// sequence intact. Both drops only count — the caller decides what to log.
inline bool bridge_enqueue(std::vector<BridgeFrame> &q, BridgeStats &stats,
                           uint32_t can_id, bool extended,
                           const std::vector<uint8_t> &data)
{
  if (data.size() > CAN_FRAME_MAX) {
    stats.dropped_oversize++;
    return false;
  }
  if (q.size() >= BRIDGE_QUEUE_MAX) {
    stats.dropped_overflow++;
    return false;
  }
  BridgeFrame f{};
  f.can_id = can_id;
  f.extended = extended;
  f.len = (uint8_t) data.size();
  for (std::size_t i = 0; i < data.size(); ++i)
    f.data[i] = data[i];
  q.push_back(f);
  stats.enqueued++;
  return true;
}

// Take up to max_frames from the front of the queue, oldest first. The O(n)
// front-erase is trivially cheap at these sizes (same trade as ha_arbitration.h).
inline std::vector<BridgeFrame> bridge_drain(std::vector<BridgeFrame> &q, BridgeStats &stats,
                                             std::size_t max_frames = BRIDGE_DRAIN_MAX)
{
  std::vector<BridgeFrame> out;
  while (!q.empty() && out.size() < max_frames) {
    out.push_back(q.front());
    q.erase(q.begin());
  }
  stats.forwarded += (uint32_t) out.size();
  return out;
}

// Heartbeat error flags from both directions' stats: any drop, ever, latches
// ERR_BRIDGE_QUEUE_OVERFLOW (stats are cumulative, so this is sticky by
// construction).
inline uint8_t bridge_error_flags(const BridgeStats &to_backbone, const BridgeStats &to_zone)
{
  const uint32_t drops = to_backbone.dropped_overflow + to_backbone.dropped_oversize +
                         to_zone.dropped_overflow + to_zone.dropped_oversize;
  return drops > 0 ? ERR_BRIDGE_QUEUE_OVERFLOW : ERR_NONE;
}

// The bridge's queues and counters. Owned here instead of ESPHome `globals:`
// entries because ESPHome emits globals storage declarations before user
// includes in the generated main.cpp, so a custom struct type never compiles
// as a global (same reasoning as ha_arbitration.h).
inline std::vector<BridgeFrame> &bridge_queue_to_backbone()
{
  static std::vector<BridgeFrame> store;
  return store;
}

inline std::vector<BridgeFrame> &bridge_queue_to_zone()
{
  static std::vector<BridgeFrame> store;
  return store;
}

inline BridgeStats &bridge_stats_to_backbone()
{
  static BridgeStats store{};
  return store;
}

inline BridgeStats &bridge_stats_to_zone()
{
  static BridgeStats store{};
  return store;
}
