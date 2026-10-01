---
description: Print the graph of a Sigil file (terminal drawing plus lint summary)
argument-hint: <file.sigil> [--depth N|all] [--payloads]
---

Show the structure of the Sigil document $1 using the sigil skill's viewer.

1. Run: `python3 @SCRIPTS@/view.py $ARGUMENTS --once`
   (if no `--depth` was given, the default is 1).
2. Show the drawing to the user verbatim in a plain code block.
3. If the lint summary reports issues, list them with a one-line suggested fix
   each. Do not edit the file unless asked.
4. Mention that `python3 @SCRIPTS@/view.py $1` (without `--once`) opens a live
   view in their own terminal that redraws every time the file is saved.
