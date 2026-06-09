---
title: 'Interactive commissioning CLI for commission.py'
type: 'feature'
created: '2026-06-09'
status: 'done'
baseline_commit: 'c8f2d63db35846140ee8473e15441d5763f0d6cf'
context: ['{project-root}/_bmad-output/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `commission.py` is a static argparse-only tool. Commissioning a freshly-mounted node means hand-typing `assign --node-id N --room R --board B …`, which is error-prone at the bench and unfriendly when commissioning several nodes in one session.

**Approach:** Add an interactive menu that launches when `commission.py` is run with no subcommand. The menu asks what to do (list or commission); commissioning prompts for each field one at a time, applies the assignment, regenerates `node_map.h`, then asks whether to commission another node. The existing `list` and `assign` subcommands remain for scripting.

## Boundaries & Constraints

**Always:**
- Running `commission.py` with no arguments launches the interactive menu.
- `list` and `assign` subcommands keep their current signatures and behavior.
- During commissioning, prompt for one field at a time in this order: node_id, room, board, floor, location.
- The entered node_id MUST already exist in `nodes.csv`; reject and re-prompt otherwise (it is allocated by `allocate_node.py`, never created here).
- Validate each numeric field on entry and re-prompt on bad input (room/board 0–255; node_id/floor non-negative ints).
- Regenerate `node_map.h` (via `generate_nodes.main()`) and print the "reflash the gateway" notice after each successful node assignment.
- After each commissioned node, ask whether to commission another; loop until the user declines, then return to the main menu. Commissioning another should be the default.
- Reuse a single shared assignment routine for both the `assign` subcommand and the interactive path — no duplicated write/regen logic.

**Ask First:**
- Adding any third-party dependency (project is stdlib-only).
- Changing `nodes.csv` columns or the assignment semantics of the `assign` subcommand.

**Never:**
- Never create new node_ids here or write rows that don't already exist.
- Never hand-edit files under `firmware/nodes/` — regeneration goes through `generate_nodes.main()`.
- No new packages — stdlib only (`argparse`, `csv`, `pathlib`).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No-arg launch | `python commission.py` | Interactive menu printed; awaits choice | N/A |
| Commission valid node | node_id in csv, room/board in range | Row updated, `node_map.h` regenerated, notice printed | N/A |
| Unknown node_id | node_id not in csv | Re-prompt with "not in nodes.csv — allocate it first" message | Loop, no write |
| Out-of-range room/board | e.g. `300` | Re-prompt with valid range hint | Loop, no write |
| Non-integer numeric input | e.g. `abc` for room | Re-prompt with valid range hint | Loop, no write |
| Blank optional field | Enter pressed on floor/location prompt | Keep the row's existing value for that field | N/A |
| Add-another = no | user declines after a node | Return to main menu | N/A |
| Quit / Ctrl-D / Ctrl-C | at any prompt | Exit cleanly, no traceback | Graceful exit |

</frozen-after-approval>

## Code Map

- `firmware/tools/commission.py` -- the only file changed; add interactive flow + shared assignment helper, make subcommand optional
- `firmware/tools/allocate_node.py` -- reference only: how rows are seeded (identity-only placeholders); do not change
- `firmware/tools/generate_nodes.py` -- `main()` regenerates `node_map.h`; called as-is after each assignment
- `firmware/registry/nodes.csv` -- the registry edited in place; columns `node_id,floor,room,board,location`

## Tasks & Acceptance

**Execution:**
- [x] `firmware/tools/commission.py` -- Extract the room/board range checks, row lookup, field update, `write_rows`, and `generate_nodes.main()` call from `cmd_assign` into a shared `apply_assignment(rows, node_id, *, room, board, floor, location)` helper (each field optional/keep-existing when `None`). Have `cmd_assign` call it. -- removes duplication so both entry points stay in sync
- [x] `firmware/tools/commission.py` -- Add prompt helpers: `prompt_int(label, lo, hi, current)` that re-prompts on non-int / out-of-range and returns current on blank; `prompt_str(label, current)`. Handle EOF/`KeyboardInterrupt` as clean exit. -- one-field-at-a-time input with validation
- [x] `firmware/tools/commission.py` -- Add `commission_interactive()`: prompt node_id (must exist in `nodes.csv`, else re-prompt), then room/board/floor/location one at a time, call `apply_assignment`, then ask "Commission another node? [Y/n]" (default yes) and loop. -- the commissioning flow
- [x] `firmware/tools/commission.py` -- Add `main_menu()` loop offering: list nodes / commission a node / quit; wire `cmd_list` and `commission_interactive`. -- "ask what I want to do"
- [x] `firmware/tools/commission.py` -- In `main()`, make the subparser optional (`required=False`); when no subcommand is given, call `main_menu()`. -- no-arg launch

**Acceptance Criteria:**
- Given a clean checkout, when I run `python commission.py` with no args, then I see a menu asking what to do and can choose to list or commission.
- Given an allocated-but-unassigned node_id, when I commission it interactively and answer each prompt, then `nodes.csv` is updated, `node_map.h` is regenerated, the reflash notice prints, and I am asked whether to commission another.
- Given I type a node_id absent from `nodes.csv` or an out-of-range room/board, when I submit it, then I am re-prompted and no row is written.
- Given the existing scripts, when I run `python commission.py list` and `python commission.py assign --node-id … --room … --board …`, then they behave exactly as before.

## Design Notes

Keep the prompt loop simple and stdlib-only. Blank input (just Enter) means "keep current value" — useful because `allocate_node.py` seeds placeholder room/board/floor/location, and re-commissioning shouldn't force re-typing unchanged fields. Surface any error raised by `generate_nodes.main()` (it `sys.exit()`s — i.e. raises `SystemExit` — when the registry has a bad row, e.g. a non-numeric or out-of-range value, or a duplicate `node_id`) without crashing the menu — catch `SystemExit`, print, and continue the loop. Note: `generate_nodes` does NOT validate `(room, board)` uniqueness (see deferred-work).

## Verification

**Commands:**
- `cd firmware/tools && python commission.py list` -- expected: registry table prints unchanged (regression check)
- `cd firmware/tools && python commission.py assign --node-id 100 --room 7 --board 0` -- expected: assigns and regenerates as before
- `cd firmware/tools && printf '2\n100\n7\n0\n0\nGround floor hallway\nn\nq\n' | python commission.py` -- expected: menu → commission node 100 → fields accepted → node_map.h regenerated + notice → declines another → quits cleanly, no traceback

**Manual checks:**
- Run `python commission.py` interactively: typing an unknown node_id and an out-of-range room each re-prompt without writing; Ctrl-C / Ctrl-D exit without a traceback.

## Suggested Review Order

**Routing into the interactive flow**

- Entry point — bare invocation drops into the menu; subcommands still dispatch.
  [`commission.py:188`](../../firmware/tools/commission.py#L188)
- The "what do you want to do?" menu loop wiring list / commission / quit.
  [`commission.py:158`](../../firmware/tools/commission.py#L158)

**Commissioning flow**

- The one-prompt-at-a-time loop: node_id existence check, fields, apply, ask-another.
  [`commission.py:124`](../../firmware/tools/commission.py#L124)
- Validated integer prompt — blank keeps current, re-prompts on bad input.
  [`commission.py:91`](../../firmware/tools/commission.py#L91)

**Shared write path (no duplication)**

- Single assignment routine backing both `assign` and interactive; the load-bearing change.
  [`commission.py:43`](../../firmware/tools/commission.py#L43)
- `assign` subcommand now a thin wrapper over `apply_assignment` — behavior preserved.
  [`commission.py:83`](../../firmware/tools/commission.py#L83)
