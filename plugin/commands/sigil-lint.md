---
description: Lint a Sigil file and explain each diagnostic
argument-hint: <file.sigil>
---

Validate the Sigil document $1 with the sigil skill's linter.

1. Run: `python3 @SCRIPTS@/lint.py $1`
   Exit code 0 means clean, 1 warnings only, 2 errors.
2. For each `severity:line:rule: message` diagnostic, quote the offending line
   and suggest a concrete fix (consult the sigil skill's
   `references/language.md` when a rule is unclear).
3. Do not rewrite the file unless the user asks; if they do, re-run the linter
   afterwards to confirm it is clean.
