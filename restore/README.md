# Temporary: batches 3 and 4 of the final release, as text

The cloud machine that built batches 3 and 4 lost its connection to GitHub on Nov 25 (a test of old Full Cloud code
deleted its /etc), so their changes are sent here as text through GitHub's API. Delete this folder once applied.

Base: `a684076` (batch 2, merged into the release line `claude/project-thread-x72wkd` as PR #69, `54bb51c`).

| Folder | What | From -> to (local commits there) | sha256 of the joined patch |
|---|---|---|---|
| `b3/part-01.txt` ... `part-07.txt` | Batch 3: AI commands, saved chats, crew, Brain -> Learned | a684076 -> a0f7e81 | `5b256fe65b75b56e58799d2bfaca5664f930b9fe27d02a030c0973e301c9d2d9` |
| `b4/part-01.txt` ... `part-18.txt` | Batch 4: space look, Text Stories, characters, Full Cloud | a0f7e81 -> 0cd03ba | `4f351ac911be4a1dff63a092db51cee6385ba43aa631280b6b6db311b25cf9e3` |

Each patch is `git diff -U0` without `frontend/dist` (rebuild it). The parts are ASCII: every other character is
written `{U+XXXX}` and turned back by the script below. Each part was checked against its git blob id after it was
sent.

## Apply

```bash
cp -r restore /tmp/restore      # from a checkout of claude/project-thread-hqwolr
git checkout -B <your branch> a684076
python3 - <<'EOF'
import glob, hashlib, re
for b in ("b3", "b4"):
    s = "".join(open(p, encoding="ascii").read().rstrip("\n") + "\n" for p in sorted(glob.glob(f"/tmp/restore/{b}/part-*.txt")))
    s = re.sub(r"\{U\+([0-9A-F]{4,6})\}", lambda m: chr(int(m.group(1), 16)), s)  # the parts are ASCII
    open(f"/tmp/{b}.patch", "w", encoding="utf-8").write(s)
    print(b, hashlib.sha256(s.encode()).hexdigest())
EOF
# compare with the table, then:
git apply --unidiff-zero --index /tmp/b3.patch
(cd frontend && npm ci && npx tsc --noEmit -p . && npm run build) && git add -A frontend/dist
git commit -m "Final release batch 3: ClipForge AI commands, saved chats, crew check, Brain -> Learned"
git apply --unidiff-zero --index /tmp/b4.patch
(cd frontend && npx tsc --noEmit -p . && npm run build) && git add -A frontend/dist
git commit -m "Final release batch 4: space look, Text Stories, characters and look examples, Full Cloud"
```

Batch 3's own commits were: 1baecbf ClipForge AI commands, saved chats and Brain -> Learned; 9323853 Brain -> Learned:
wording, labels, Forget my edits, privacy page; e93106d Batch 3 notes; 3a67930 Learned: work chips only show your own
work in cloud mode, new clips skip learning when nothing is learned. Batch 4's: b0528b4 Space look; e72cf60 Text
Stories; b462d50 characters, look examples, Full Cloud, Settings -> Processing; 616d071 Full Cloud review fixes.

## State when sent

- Batch 3: done; fast + slow suites passed before it was merged with a684076.
- Batch 4: fast suite 3,261 passed, 2 skipped before the Full Cloud review fixes; `tests/test_full_cloud.py` 26
  passed after them. Slow suite not valid yet (run during the /etc damage). Review fixes 1-6 and 26-32 are done;
  7-25 (Text Stories, characters) are in `REMAINING.md`. Then: fast + slow suites, add their numbers to
  `docs/IMPLEMENTATION_STATUS.md` (batch 4 section), screenshots, one PR per batch into the release line.
- When testing code that deletes or moves paths, never run it against old code with real absolute paths: use the
  test's tmp folder.
