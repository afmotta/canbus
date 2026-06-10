#pragma once
#include <cstdint>
#include <cstddef>
#include <vector>

// =============================================================================
// ha_ready arbitration — ADR-0003 readiness gating + per-event ACK/fallback
// =============================================================================
//
// The controller forwards button events to HA only while HA is "ready"; otherwise
// (and when a forwarded event is not ACKed in time) the local fallback path runs.
// ha_ready is computed, never stored as authority (ADR-0003 "Binding model"):
//
//   ha_ready = api_connected && hash_ok && fresh heartbeat within TTL
//
// Pure logic only — no ESPHome includes — so the timeout machinery is natively
// testable (see tests/test_ha_arbitration.cpp). All time math uses unsigned
// uint32_t subtraction so millis() wraparound (~49.7 days) cannot wedge readiness
// or expiry, valid while TTLs/timeouts stay far below ~24.8 days (2^31 ms).
// =============================================================================

// A forwarded-to-HA event awaiting its ACK service call (event_id is a
// controller-local monotonic counter, not a protocol field).
struct PendingAck
{
  uint32_t event_id;
  uint32_t deadline_ms;
  uint16_t node_id;
  uint8_t button;
  uint8_t event_type;
};

// A recently expired entry, kept so a late ACK (arriving after its fallback fired)
// can be recognized and its lateness measured — that lateness is the double-action
// window, the key datum for tuning ack_timeout_ms (ADR-0003 open item 2).
struct ExpiredAck
{
  uint32_t event_id;
  uint32_t deadline_ms;
};

// Outstanding-ACK cap: past this, pending_add drops the oldest entry (its fallback
// is skipped). Only reachable under pathological settings (huge ack_timeout_ms with
// ACKs disabled); bounds heap growth on the ESP32.
inline constexpr std::size_t PENDING_ACKS_MAX = 64;
inline constexpr std::size_t EXPIRED_RING_MAX = 16;

// hb_seen distinguishes "never heard a heartbeat" from last_hb_ms == 0, which is a
// valid timestamp, not a sentinel (same reasoning as node_id 0). TTL is inclusive.
inline bool ha_ready(bool api_connected, bool hash_ok, bool hb_seen,
                     uint32_t last_hb_ms, uint32_t now_ms, uint32_t ttl_ms)
{
  if (!api_connected || !hash_ok || !hb_seen)
    return false;
  return (uint32_t) (now_ms - last_hb_ms) <= ttl_ms;
}

// True when now_ms is at or past deadline_ms, modulo uint32 wraparound.
inline bool deadline_passed(uint32_t now_ms, uint32_t deadline_ms)
{
  return (uint32_t) (now_ms - deadline_ms) < 0x80000000u;
}

inline void pending_add(std::vector<PendingAck> &pending, uint32_t event_id,
                        uint32_t now_ms, uint32_t timeout_ms,
                        uint16_t node_id, uint8_t button, uint8_t event_type)
{
  if (pending.size() >= PENDING_ACKS_MAX)
    pending.erase(pending.begin());
  pending.push_back({event_id, (uint32_t) (now_ms + timeout_ms), node_id, button, event_type});
}

// The controller's pending-ACK list and expired-entry ring. Owned here instead of
// ESPHome `globals:` entries because ESPHome emits globals storage declarations
// before user includes in the generated main.cpp, so a custom struct type never
// compiles as a global.
inline std::vector<PendingAck> &pending_acks_store()
{
  static std::vector<PendingAck> store;
  return store;
}

inline std::vector<ExpiredAck> &expired_ring_store()
{
  static std::vector<ExpiredAck> store;
  return store;
}

// Remove the entry matching event_id; true if found (the normal ACK path), with the
// matched entry copied to *acked so the caller can log the ACK round-trip time.
// False = unknown or already-expired event_id; callers consult the expired ring.
inline bool pending_ack(std::vector<PendingAck> &pending, uint32_t event_id,
                        PendingAck *acked = nullptr)
{
  for (std::size_t i = 0; i < pending.size(); ++i) {
    if (pending[i].event_id == event_id) {
      if (acked != nullptr)
        *acked = pending[i];
      pending.erase(pending.begin() + i);
      return true;
    }
  }
  return false;
}

inline void expired_record(std::vector<ExpiredAck> &ring, uint32_t event_id, uint32_t deadline_ms)
{
  if (ring.size() >= EXPIRED_RING_MAX)
    ring.erase(ring.begin());
  ring.push_back({event_id, deadline_ms});
}

// Find and consume a recently expired event_id; true if found, its deadline in
// *deadline_ms (lateness = now - deadline).
inline bool expired_take(std::vector<ExpiredAck> &ring, uint32_t event_id, uint32_t *deadline_ms)
{
  for (std::size_t i = 0; i < ring.size(); ++i) {
    if (ring[i].event_id == event_id) {
      if (deadline_ms != nullptr)
        *deadline_ms = ring[i].deadline_ms;
      ring.erase(ring.begin() + i);
      return true;
    }
  }
  return false;
}

// Move expired entries out of pending and return them, so each event's fallback
// fires at most once. Home-scale event rates make the O(n) sweep trivially cheap.
inline std::vector<PendingAck> pending_expire(std::vector<PendingAck> &pending, uint32_t now_ms)
{
  std::vector<PendingAck> expired;
  for (std::size_t i = 0; i < pending.size();) {
    if (deadline_passed(now_ms, pending[i].deadline_ms)) {
      expired.push_back(pending[i]);
      pending.erase(pending.begin() + i);
    } else {
      ++i;
    }
  }
  return expired;
}
