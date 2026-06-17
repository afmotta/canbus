// Standalone native test for node_health.h (no ESPHome required).
// Build & run:  g++ -std=c++17 -Wall -Wextra firmware/tests/test_node_health.cpp -o /tmp/health && /tmp/health
//
// Covers the ADR-0011 aliveness logic: heartbeat edge detection (recovered/error),
// the 90 s lost transition (once-only, wraparound-safe), online/missing counts, the
// declarative-node_lost announce queue, and node_id -> store-index resolution against
// the compiled node_map.h.

#include "../protocol/node_health.h"
#include "../protocol/canbus_protocol.h"   // ERR_* flags
#include <cassert>
#include <cstdio>

int main()
{
  const uint32_t T = 90000;  // node_lost_timeout_ms (3x 30 s cadence)

  // --- first sighting, clean: seen, stamped, NO edge ---
  NodeHealth h{};
  assert(health_on_heartbeat(h, 1000, ERR_NONE) == HEALTH_EDGE_NONE);
  assert(h.seen && !h.lost && h.last_seen_ms == 1000 && h.error_flags == ERR_NONE);

  // --- still fresh at and just past the boundary; lost strictly after timeout ---
  assert(!health_check_lost(h, 1000 + T, T));        // exactly at timeout: not yet lost
  assert(health_check_lost(h, 1000 + T + 1, T));     // one ms past: LOST (fires once)
  assert(h.lost);
  assert(!health_check_lost(h, 1000 + T + 5000, T)); // already lost: idempotent, no re-fire

  // --- a lost node is missing and not online ---
  assert(health_is_missing(h));

  // --- announcing the loss (sweep fired canbus_node_lost) is what arms RECOVERED ---
  assert(health_take_unannounced_lost(&h, 1) == 0 && h.lost_announced);
  // --- recovery: heartbeat after an ANNOUNCED loss fires RECOVERED, clears lost ---
  assert(health_on_heartbeat(h, 200000, ERR_NONE) == HEALTH_EDGE_RECOVERED);
  assert(!h.lost && !health_is_missing(h));

  // --- orphan prevention: a loss that resolves BEFORE it was announced surfaces NOTHING ---
  // (no canbus_node_lost was sent, so no canbus_node_recovered may be sent either).
  NodeHealth q{};
  health_on_heartbeat(q, 1000, ERR_NONE);
  assert(health_check_lost(q, 1000 + T + 1, T) && q.lost && !q.lost_announced);
  assert(health_on_heartbeat(q, 250000, ERR_NONE) == HEALTH_EDGE_NONE);  // no orphan RECOVERED
  assert(!q.lost);
  assert(health_take_unannounced_lost(&q, 1) == -1);  // the pending loss was cancelled, not dropped

  // --- recover + still-changed flags in one heartbeat fires BOTH edges ---
  NodeHealth r{};
  health_on_heartbeat(r, 1000, ERR_CAN_BUS_OFF);            // boots with a flag
  assert(health_check_lost(r, 1000 + T + 1, T));
  assert(health_take_unannounced_lost(&r, 1) == 0);         // announced lost
  uint8_t both = health_on_heartbeat(r, 300000, ERR_CAN_TX_FAIL);  // returns with a different flag
  assert((both & HEALTH_EDGE_RECOVERED) && (both & HEALTH_EDGE_ERROR));

  // --- error edge: flags change fires ERROR; unchanged flags do NOT (no per-30 s spam) ---
  assert(health_on_heartbeat(h, 230000, ERR_CAN_BUS_OFF) == HEALTH_EDGE_ERROR);
  assert(h.error_flags == ERR_CAN_BUS_OFF);
  assert(health_on_heartbeat(h, 260000, ERR_CAN_BUS_OFF) == HEALTH_EDGE_NONE);  // same flags
  assert(health_on_heartbeat(h, 290000, ERR_NONE) == HEALTH_EDGE_ERROR);        // clearing to 0 is a change

  // --- first sighting carrying an error fires ERROR immediately ---
  NodeHealth boot{};
  assert(health_on_heartbeat(boot, 500, ERR_CAN_TX_FAIL) == HEALTH_EDGE_ERROR);

  // --- lost transition across millis() wraparound ---
  NodeHealth w{};
  health_on_heartbeat(w, 0xFFFFFF00u, ERR_NONE);      // last_seen just before wrap
  assert(!health_check_lost(w, 0x00000100u, T));       // diff = 512 ms, still fresh
  assert(health_check_lost(w, 0xFFFFFF00u + T + 1, T)); // diff just past timeout: LOST

  // --- online / missing counts over an array ---
  NodeHealth fleet[3] = {};
  assert(health_nodes_online(fleet, 3) == 0);          // none heard yet -> all missing
  health_on_heartbeat(fleet[0], 1000, ERR_NONE);
  health_on_heartbeat(fleet[2], 1000, ERR_NONE);
  assert(health_nodes_online(fleet, 3) == 2);          // [1] never seen -> still missing
  assert(health_is_missing(fleet[1]));
  health_check_lost(fleet[2], 1000 + T + 1, T);        // [2] goes silent
  assert(health_nodes_online(fleet, 3) == 1);

  // --- announce queue: one node_lost per call, no simultaneous loss dropped ---
  NodeHealth pair[2] = {};
  health_on_heartbeat(pair[0], 1000, ERR_NONE);
  health_on_heartbeat(pair[1], 1000, ERR_NONE);
  assert(health_check_lost(pair[0], 1000 + T + 1, T)); // both lost in the same sweep
  assert(health_check_lost(pair[1], 1000 + T + 1, T));
  int a = health_take_unannounced_lost(pair, 2);
  int b = health_take_unannounced_lost(pair, 2);
  assert(a == 0 && b == 1);                            // both announced, distinct indices...
  assert(health_take_unannounced_lost(pair, 2) == -1); // ...then nothing left
  // recovery re-arms announcement for a future loss
  health_on_heartbeat(pair[0], 2 * T, ERR_NONE);
  assert(!pair[0].lost_announced);
  assert(health_check_lost(pair[0], 2 * T + T + 1, T));
  assert(health_take_unannounced_lost(pair, 2) == 0);  // re-announced

  // --- node_id -> store index against the compiled map (node_map.h: 100, 101) ---
  assert(node_health_index(100) == 0);
  assert(node_health_index(101) == 1);
  assert(node_health_index(999) == -1);                // unmapped: not health-tracked
  // Robust to map regeneration: every mapped id resolves to its own NODE_MAP slot.
  for (std::size_t i = 0; i < NODE_MAP_SIZE; i++)
    assert(node_health_index(NODE_MAP[i].node_id) == (int) i);

  printf("test_node_health: all assertions passed\n");
  return 0;
}
