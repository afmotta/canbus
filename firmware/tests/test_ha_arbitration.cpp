// Standalone native test for ha_arbitration.h (no ESPHome required).
// Build & run:  g++ -std=c++17 -Wall -Wextra firmware/tests/test_ha_arbitration.cpp -o /tmp/arb && /tmp/arb
//
// Covers the ADR-0003 ha_ready gating truth table (incl. the inclusive TTL boundary
// and millis() wraparound) and the pending-ACK add/ack/expire machinery.

#include "../protocol/ha_arbitration.h"
#include <cassert>
#include <cstdio>

int main()
{
  // --- ha_ready truth table ---
  assert(ha_ready(true, true, true, 1000, 1000, 15000));    // fresh heartbeat
  assert(ha_ready(true, true, true, 1000, 16000, 15000));   // exactly at TTL (inclusive)
  assert(!ha_ready(true, true, true, 1000, 16001, 15000));  // one past TTL
  assert(!ha_ready(false, true, true, 1000, 1000, 15000));  // API disconnected
  assert(!ha_ready(true, false, true, 1000, 1000, 15000));  // manifest hash mismatch
  assert(!ha_ready(true, true, false, 1000, 1000, 15000));  // no heartbeat ever seen
  // last_hb_ms == 0 is a valid timestamp only once hb_seen says so
  assert(!ha_ready(true, true, false, 0, 0, 15000));
  assert(ha_ready(true, true, true, 0, 0, 15000));

  // --- ha_ready across millis() wraparound ---
  // heartbeat just before wrap, now just after: diff = 512 ms, still fresh
  assert(ha_ready(true, true, true, 0xFFFFFF00u, 0x00000100u, 15000));
  // same wrap but diff = 16640 ms > TTL
  assert(!ha_ready(true, true, true, 0xFFFFFF00u, 0x00004000u, 15000));

  // --- deadline_passed half-range boundary (the 2^31 ms wraparound contract) ---
  assert(deadline_passed(1000, 1000));                       // at the deadline
  assert(deadline_passed(1000 + 0x7FFFFFFFu, 1000));         // just inside half range
  assert(!deadline_passed(1000 + 0x80000000u, 1000));        // half range reads as "before"

  // --- pending add / ack ---
  std::vector<PendingAck> p;
  pending_add(p, 1, 1000, 500, 100, 3, 2);
  pending_add(p, 2, 1100, 500, 101, 0, 1);
  assert(p.size() == 2);
  assert(p[0].deadline_ms == 1500 && p[0].node_id == 100 && p[0].button == 3 && p[0].event_type == 2);
  PendingAck acked{};
  assert(pending_ack(p, 1, &acked));            // normal ACK removes the entry...
  assert(acked.deadline_ms == 1500 && acked.node_id == 100);  // ...and hands it back (rtt logging)
  assert(p.size() == 1 && p[0].event_id == 2);
  assert(!pending_ack(p, 99));                  // unknown ACK is ignored
  assert(p.size() == 1);

  // --- pending cap: oldest dropped past PENDING_ACKS_MAX ---
  std::vector<PendingAck> q;
  for (uint32_t i = 0; i < PENDING_ACKS_MAX + 5; ++i)
    pending_add(q, i, 0, 100, 1, 1, 1);
  assert(q.size() == PENDING_ACKS_MAX && q[0].event_id == 5);

  // --- expired ring: record, consume-once, bounded eviction ---
  std::vector<ExpiredAck> ring;
  expired_record(ring, 7, 5000);
  uint32_t dl = 0;
  assert(expired_take(ring, 7, &dl) && dl == 5000);   // late ACK finds its deadline
  assert(!expired_take(ring, 7, &dl));                // consumed — no double match
  for (uint32_t i = 0; i < EXPIRED_RING_MAX + 4; ++i)
    expired_record(ring, 100 + i, i);
  assert(ring.size() == EXPIRED_RING_MAX);            // bounded
  assert(!expired_take(ring, 100, &dl));              // oldest evicted
  assert(expired_take(ring, 100 + EXPIRED_RING_MAX + 3, &dl));  // newest present

  // --- expiry: each entry fires at most once; unexpired entries stay ---
  pending_add(p, 3, 1200, 500, 102, 7, 5);      // deadline 1700
  auto expired = pending_expire(p, 1650);       // event 2 (deadline 1600) expires
  assert(expired.size() == 1 && expired[0].event_id == 2);
  assert(p.size() == 1 && p[0].event_id == 3);
  assert(pending_expire(p, 1650).empty());      // no double fire
  expired = pending_expire(p, 1700);            // deadline == now counts as passed
  assert(expired.size() == 1 && expired[0].event_id == 3 && expired[0].node_id == 102);
  assert(p.empty());

  // --- expiry across millis() wraparound (deadline itself wraps) ---
  pending_add(p, 4, 0xFFFFFFF0u, 0x100, 1, 1, 1);  // deadline wraps to 0x000000F0
  assert(pending_expire(p, 0x00000010u).empty());  // wrapped, but before the deadline
  expired = pending_expire(p, 0x000000F0u);        // at the wrapped deadline
  assert(expired.size() == 1 && expired[0].event_id == 4);
  assert(p.empty());

  printf("test_ha_arbitration: all assertions passed\n");
  return 0;
}
