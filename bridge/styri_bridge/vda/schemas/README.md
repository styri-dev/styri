# VDA 5050 JSON schemas

The official schemas from <https://github.com/VDA5050/VDA5050>, branch
`release/2.1.0` (commit 907c183), under the MIT license in `LICENSE.txt`.

Modified by Styri, because the published files have two defects:

- `state.schema`: `PAUSED` added to `actionStatus`. The field's own description
  lists it, and the enum leaves it out.
- `factsheet.schema`: in `blockingTypes`, the enum moved from the array to its
  items, so a valid list of blocking types can pass.

The files are reformatted by those edits. Nothing else changed.
