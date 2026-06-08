#pragma once
#include <cstdint>
#include <cstddef>

// =============================================================================
// node_map.h — GENERATED from nodes.csv by generate_nodes.py. DO NOT EDIT.
// Central node_id -> {room, board, name} map (ADR-0007), compiled into the gateway.
// An unknown node_id resolves to the sentinel (room/board 0xFF, name "unknown") —
// i.e. a node that is on the bus but not yet in the map (uncommissioned).
// =============================================================================

struct NodeMapEntry { uint16_t node_id; uint8_t room; uint8_t board; const char *name; };

inline constexpr uint8_t NODE_MAP_UNKNOWN = 0xFF;

inline constexpr NodeMapEntry NODE_MAP[] = {
    {100, 7, 0, "Ground floor hallway"},
    {101, 8, 0, "Ground floor living room"},
};
inline constexpr std::size_t NODE_MAP_SIZE = sizeof(NODE_MAP) / sizeof(NODE_MAP[0]);

inline const NodeMapEntry *node_map_find(uint16_t node_id) {
  for (std::size_t i = 0; i < NODE_MAP_SIZE; i++)
    if (NODE_MAP[i].node_id == node_id) return &NODE_MAP[i];
  return nullptr;
}
inline bool node_map_known(uint16_t node_id) { return node_map_find(node_id) != nullptr; }
inline uint8_t node_map_room(uint16_t node_id) { auto e = node_map_find(node_id); return e ? e->room : NODE_MAP_UNKNOWN; }
inline uint8_t node_map_board(uint16_t node_id) { auto e = node_map_find(node_id); return e ? e->board : NODE_MAP_UNKNOWN; }
inline const char *node_map_name(uint16_t node_id) { auto e = node_map_find(node_id); return e ? e->name : "unknown"; }
