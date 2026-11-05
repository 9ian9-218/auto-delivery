# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| :------------------------- | :------------------- | :--------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

These five labels all exist in `9ian9-218/jevlike_broswer` (`wontfix` came with the GitHub defaults; the other four were created at setup). Apply them as-is; only edit the "Label in our tracker" column if the repo's vocabulary actually changes.

## Wayfinder labels (separate family, not triage)

`/wayfinder` maps and tickets carry **only** `wayfinder:` labels, never a triage label (`wayfinder` treats its tickets as decisions, not implementation work):

| Label                 | Used on                                             |
| :-------------------- | :-------------------------------------------------- |
| `wayfinder:map`       | the map issue (the planning artifact)               |
| `wayfinder:research`  | a decision ticket resolved by research              |
| `wayfinder:prototype` | a decision ticket resolved by a throwaway prototype |
| `wayfinder:grilling`  | a decision ticket resolved by grilling the human    |
| `wayfinder:task`      | a decision ticket resolved by doing a concrete task |

All five exist in the repo. Do not add a triage label to a map or to a wayfinder ticket.
