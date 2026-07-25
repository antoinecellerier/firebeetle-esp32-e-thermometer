---
name: claude-md-audit
description: >-
  Audit CLAUDE.md and the .claude/rules files for accuracy and bloat, and propose
  a concrete edit list. Run this BEFORE committing any change to CLAUDE.md (the
  file's own house rules require it), and periodically as a maintenance pass. It
  verifies every reference still resolves (paths, docs links, commit hashes, make
  targets, env names), flags references to gitignored paths, checks the loaded
  line budget, finds duplication across CLAUDE.md / .claude/rules / docs / memory
  / skills, and scans recent session transcripts for durable rules worth promoting
  or rules now stale. Use when the user asks to "audit / clean up / prune
  CLAUDE.md" or before a CLAUDE.md commit.
---

# claude-md-audit

CLAUDE.md loads every session, so it bloats over time: each session *adds* a rule
or a trap, nothing *removes*. This audit is the forcing function. It produces a
punch list of concrete add / remove / relocate edits — **present them to the
user; do not auto-apply.**

Scope is `CLAUDE.md`, `.claude/rules/*.md`, `.claude/skills/*/SKILL.md` and
`hardware/thermometer-c6/CLAUDE.md`.

## 1. Reference accuracy

Every file path, make target, script, env name, `docs/` link, commit hash,
function name, macro and CLI flag named in these files must still resolve:

```bash
# paths and docs links
grep -ohE '`[a-zA-Z0-9_./-]+\.(md|py|c|h|cpp|csv|ini|json)`' CLAUDE.md .claude/rules/*.md \
  | tr -d '`' | sort -u | while read -r p; do test -e "$p" || echo "MISSING $p"; done
# commit hashes
grep -ohE '`[0-9a-f]{7,40}`' CLAUDE.md .claude/rules/*.md | tr -d '`' | sort -u \
  | while read -r h; do [ "$(git cat-file -t "$h" 2>&1)" = commit ] || echo "BAD HASH $h"; done
# pio envs
grep -oE '\-e [a-z0-9_]+' CLAUDE.md | awk '{print $2}' | sort -u \
  | while read -r e; do grep -q "^\[env:$e\]" platformio.ini || echo "NO ENV $e"; done
```

Also check make targets exist (`grep -E '^[a-z_-]+:' tools/*/Makefile`) and that
macro/function names still appear in the sources.

Flag each stale reference with what it should point to now.

## 2. Portability — nothing tied to one clone or one machine

These are tracked files that must work in any clone. Two classes of violation:

**Environment-specific absolute paths.** No `/home/<user>/...`, no session or
transcript directories spelled out, no machine-local scratch paths. Derive them
instead (`$HOME`, `$(pwd)`, repo-relative). `~/.platformio/...` is fine — that is
where PlatformIO installs for everyone.

```bash
grep -rnE '/home/[a-z]+|/Users/[a-z]+' CLAUDE.md .claude/rules .claude/skills docs/*.md
```

**References to specific gitignored files** — they rot on clone. Check
`.gitignore`, then grep for paths under each ignored tree (`include/generated/`,
`/scratchpad/`, `sdkconfig.<env>`, `.pio`, `include/local-secrets.h`). Only the
first case below is a violation:

- **Violation:** a path to a specific gitignored file, e.g.
  `include/generated/fonts.h`. Propose stating the lesson directly.
- **Allowed:** stating the convention itself, e.g. "sensor/display selection
  lives in `include/local-secrets.h`" or "bench scratch goes in `/scratchpad/`".
  Those are the rule text and must stay.

`.claude/settings.local.json` is exempt from both — it is gitignored and local by
design.

## 3. Bloat

Report the **loaded** line count vs the budget in the house-rules header
(currently ~130). Count only what enters context — exclude the leading
block-level HTML comment, which Claude Code strips before injection:

```bash
python3 -c "
import re; s=open('CLAUDE.md').read()
print(len(re.sub(r'<!--.*?-->','',s,flags=re.S).splitlines()))"
```

If over, flag the longest prose passages and propose relocating: rationale to
`docs/`, a multi-step procedure to a skill, and anything that only matters when
specific files are touched to a `.claude/rules/` file with a `paths:` glob. Those
cost nothing until a matching file is opened, which is the main lever here.

## 4. Duplication

Find content repeated across CLAUDE.md, `.claude/rules/`, `docs/`, the skills,
and the auto-memory files (`$SESSIONS/memory/`, see below). Each fact should have
one home: the *rule* in CLAUDE.md or a rule file, the *rationale/evidence* in
`docs/`, the *procedure* in a skill. This repo also keeps design rationale in
source header comments (`include/HistoryStore.h`) — that counts as a home.
Recommend collapsing duplicates to a pointer.

## 5. Friction scan — what to promote

Skim recent session transcripts for durable rules the user has stated more than
once that are NOT yet captured. Claude Code stores them per working directory,
under the absolute path with `/` replaced by `-`, so derive the directory rather
than hardcoding it:

```bash
SESSIONS="$HOME/.claude/projects/$(pwd | tr '/' '-')"
ls -t "$SESSIONS"/*.jsonl | head -5
```

Useful extraction (tool results are `type=="user"` too, so filter to text
blocks, and drop the subagent reports which dominate by volume):

```bash
jq -r 'select(.type=="user" and (.isMeta|not)) | .message.content
       | if type=="string" then . else (map(select(.type=="text").text)|join("\n")) end' \
  "$SESSIONS/<session>.jsonl" \
  | perl -0777 -pe 's{<task-notification>.*?</task-notification>}{}gs'
```

Look for correction markers ("no", "don't", "actually", "I thought", "why are
we", "that's not"), rejected tool uses, and repeated constraints. Also check the
`ReportFindings` payloads from past `/code-review` runs — a finding class that
recurs belongs in a rule file.

A rule belongs in CLAUDE.md only if it's a durable project rule not derivable
from the code. Subsystem-specific ones belong in `.claude/rules/`.

## 6. Stale rules and session narration

Flag rules that no longer apply: an investigation flag that was reverted, a file
or feature that was removed, a trap now structurally impossible, a measured figure
whose conditions no longer hold. Check the memory files too — they carry dates and
model names that go stale.

Also flag **narration of the session that produced the rule** — "three separate
bugs shipped here on <date>", "this cost four round-trips", a list of commit
hashes standing in for the invariant. Instructions state the current rule; git
holds the history. Propose rewriting each as the durable principle. Dated *state*
is the exception and should keep its date (which rig is on the bench, what a soak
is running).

## 7. Numbers hygiene

This project's rules quote measured figures. Verify each is still sourced:
device-intrinsic costs should cite a logbook entry (`docs/notes.md`,
`docs/clock-drift.md`, `docs/footprint.md`,
`docs/history-store-validation.md`), and environment-dependent figures should be
stated as an order of magnitude with their driver named, not as a constant. Flag
any bare number with no provenance.

## Output

A single punch list: for each finding, the file and line, the issue, and the
exact proposed edit (add / remove / relocate). End with the projected new loaded
line count if all edits are applied. Hand it to the user to approve before
editing.
