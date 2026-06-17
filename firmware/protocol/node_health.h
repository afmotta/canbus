#pragma once
#include <cstdint>
#include <cstddef>
#include "node_map.h"   // NODE_MAP / NODE_MAP_SIZE / node_map_find (GENERATED, ADR-0007)

// =============================================================================
// node_health.h — gateway-resident aliveness (ADR-0011 §1)
// =============================================================================
//
// The gateway is the only component that can know a mapped node went silent: it
// holds the compiled fleet (node_map.h, ADR-0009) and hears every heartbeat. This
// header tracks last_seen per MAPPED node and derives the edge events + aggregates
// the gateway forwards to HA (ADR-0011 §2: edges and aggregates, never streams).
//
// One staleness doctrine (ADR-0011 §1, shared with ADR-0006): a node is LOST after
// 3 missed 30 s heartbeats (90 s) — passed in as timeout_ms so it stays a tunable
// substitution. Pure logic only — no ESPHome includes — so the transition machinery
// is natively testable (see tests/test_node_health.cpp), exactly like ha_arbitration.h.
// All time math uses unsigned uint32_t subtraction so millis() wraparound (~49.7 days)
// cannot wedge loss detection.
// =============================================================================

// Per-mapped-node watch state. RAM-only by decision (ADR-0011 negative consequence):
// a gateway reboot zeroes this and re-learns within one heartbeat period (~30 s).
struct NodeHealth
{
  uint32_t last_seen_ms;    // millis() of the most recent heartbeat
  bool     seen;            // have we ever heard this node? (last_seen_ms == 0 is a valid stamp)
  bool     lost;            // latched: heard before, now silent past the timeout
  bool     lost_announced;  // the canbus_node_lost edge has been fired for the current loss
  uint8_t  error_flags;     // error_flags carried by the last heartbeat
};

// Which edge events a single heartbeat triggered (bitmask). canbus_node_lost is NOT
// here — it is absence-detected by the sweep (health_check_lost), not frame-triggered.
inline constexpr uint8_t HEALTH_EDGE_NONE      = 0x00;
inline constexpr uint8_t HEALTH_EDGE_RECOVERED = 0x01; // was lost, heard again
inline constexpr uint8_t HEALTH_EDGE_ERROR     = 0x02; // error_flags changed value (incl. clearing to 0)

// Record a heartbeat from a mapped node; returns the edge bitmask the caller should fire.
// First sighting fires no RECOVERED (it was never lost) and fires ERROR only if the node
// boots already carrying flags. A node that keeps reporting the same flags every 30 s
// fires ERROR once (on change), not on every heartbeat.
//
// RECOVERED fires only if the loss was actually ANNOUNCED (canbus_node_lost already sent).
// A node that goes silent and returns before the sweep announced it (e.g. one of several
// simultaneous losses still queued behind the one-per-tick announce) surfaced nothing to
// HA, so it must surface nothing on return — otherwise HA gets an orphan "recovered" with
// no preceding "lost". This keeps every recovered edge paired with a prior lost edge.
inline uint8_t health_on_heartbeat(NodeHealth &h, uint32_t now_ms, uint8_t error_flags)
{
  uint8_t edges = HEALTH_EDGE_NONE;
  if (h.seen && h.lost && h.lost_announced)
    edges |= HEALTH_EDGE_RECOVERED;
  if (error_flags != h.error_flags)
    edges |= HEALTH_EDGE_ERROR;
  h.seen = true;
  h.lost = false;
  h.lost_announced = false;   // back online: a future loss starts a fresh announce cycle
  h.last_seen_ms = now_ms;
  h.error_flags = error_flags;
  return edges;
}

// Sweep one node for the silence transition. Returns true EXACTLY on the seen && !lost
// -> lost edge so aggregates flip once; a never-seen node never goes "lost" (it is
// "missing" instead — see health_is_missing). timeout_ms = 3x heartbeat cadence (90 s).
inline bool health_check_lost(NodeHealth &h, uint32_t now_ms, uint32_t timeout_ms)
{
  if (!h.seen || h.lost)
    return false;
  if ((uint32_t) (now_ms - h.last_seen_ms) > timeout_ms) {
    h.lost = true;
    return true;
  }
  return false;
}

// Missing = not part of the heard fleet right now: either never seen (mapped but never
// commissioned / silent since boot) or lost. Drives the nodes_missing aggregate.
inline bool health_is_missing(const NodeHealth &h) { return !h.seen || h.lost; }

// Online = heard at least once and not currently lost. nodes_total is NODE_MAP_SIZE.
inline std::size_t health_nodes_online(const NodeHealth *arr, std::size_t n)
{
  std::size_t count = 0;
  for (std::size_t i = 0; i < n; i++)
    if (arr[i].seen && !arr[i].lost)
      count++;
  return count;
}

// Index of the first node that is lost but not yet announced, marking it announced; or
// -1 if none. Lets the gateway fire ONE declarative canbus_node_lost per sweep tick
// without dropping simultaneous losses — the rest announce on subsequent ticks (the
// latched lost state already drives the aggregates immediately).
inline int health_take_unannounced_lost(NodeHealth *arr, std::size_t n)
{
  for (std::size_t i = 0; i < n; i++) {
    if (arr[i].lost && !arr[i].lost_announced) {
      arr[i].lost_announced = true;
      return (int) i;
    }
  }
  return -1;
}

// The gateway's per-node watch state: a static array sized by the compiled map. Owned
// here (not an ESPHome `global:`) because ESPHome declares globals storage before user
// includes, so a custom struct type never compiles as a global — same reason
// ha_arbitration.h owns the pending-ACK store.
inline NodeHealth *node_health_store()
{
  static NodeHealth store[NODE_MAP_SIZE ? NODE_MAP_SIZE : 1] = {};
  return store;
}

// Map a node_id to its index in the health store (its position in NODE_MAP), or -1 if
// the node is unmapped. Keeps the store in lock-step with the compiled map without
// hand-editing the generated node_map.h.
inline int node_health_index(uint16_t node_id)
{
  const NodeMapEntry *e = node_map_find(node_id);
  return e ? (int) (e - NODE_MAP) : -1;
}
