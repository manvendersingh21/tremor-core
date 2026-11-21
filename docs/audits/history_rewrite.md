# Git history rewrite

Owner approved. Removes an old private GPU box address and SSH key path from all history.

## What was removed (masked)

| Kind | Masked value | Replaced by | Seen in |
|---|---|---|---|
| Box hostname | `pr***` | `REDACTED_HOST` | 8 lines, 4 commits |
| SSH port | `30***` | `REDACTED_PORT` | 10 lines, also a doc sentence |
| Key file path | `~/ak***/id_rsa` | `REDACTED_KEY_PATH` | 8 lines |
| Key folder name | `ak***` | `REDACTED_KEY_DIR` | 8 lines |
| Tunnel local ports (`-L`) | 3 ports | `LOCAL_PORT` | 6 lines |

Commits named by the audit (`docs/audits/k2_audit.md`): 088cd85, 6177579, 65f5a53, 299e136, 7d4ebdc.
The replacement file was kept outside the repo (`/tmp`, mode 600) and is not committed.

## Shas

| | sha |
|---|---|
| Old dev | `32b962e` |
| New dev (rewritten) | `483e19d` |

All 10 branches were rewritten and force-pushed. There are no tags.

## Backup

Mirror clone of the old history: `~/Backups/tremor-core-pre-rewrite-20261121.git` (outside the repo, not pushed).
It still holds the old values. Delete it once the key is rotated.

## Scan result

- Before: every original value was found in history (8 to 10 hits each).
- After, on the rewritten mirror (all refs, patches and messages): 0 hits for each value.
- `make test` on a fresh checkout of the rewritten dev: 379 passed, 1 skipped.

## Not fixed by this rewrite

- GitHub may keep old commits in closed pull-request refs (`refs/pull/*`) and caches. Only GitHub Support can purge them. Old commit URLs may still load.
- Rotate the SSH key. Treat the old one as exposed.
- Clones on k1, k2 and the A6000 box still hold the old history. Delete them and clone again. Do not pull or merge into them.
- Other local clones and open branches built on old shas need the same treatment.
