# HACP and Claude on the Akash box

Not part of the product path. The harness never depends on this.

## Installed (on the box, no new login)
- `/root/hacp` : clone of the HACP library (source only, not built).
- `/root/hacp-skill` : clone of hacp-skill, tag v0.1.1.
- `/root/hacp-bin/bin/hacp` : hacp-skill binary built with cargo on the box. `hacp --version` prints `hacp-skill 0.1.1`.
- Claude Code 2.1.323 was already there at `~/.local/bin/claude` and already signed in. Nothing was added.

## Skipped
- `hacp install --cli claude` (puts a skill in `~/.claude`). Not run: it changes Claude config and nothing needs it.
- Anything on the Mac. hacp-skill needs two agent CLIs on one machine, so it cannot link a Mac chat to the box. It was not installed on the Mac.
- No keys, logins or passwords were set up or read.

## Send a task to Claude on the box
Host, port and key are in `~/.ssh` / `.env`. Use the Akash SSH alias or settings from there.

```
ssh <akash> 'PATH=$HOME/.local/bin:$PATH claude -p "<task>" --allowedTools "Bash(nvidia-smi:*)" "Bash(ps:*)"' </dev/null
```

Allow only the tools the task needs. Always add `</dev/null`.

## Proof (one round trip)
Task: report GPU memory and Neo4j status. Claude answered:
- GPU: 18,952 MiB of 32,768 MiB used (V100).
- Neo4j: not running.

Check done by hand on the box: `nvidia-smi` gave 18952 / 32768 MiB, and `pgrep` found no Neo4j. Both match.

## Limits
- This is plain `ssh` plus `claude -p`. It is not a HACP session: no contract, no counterparty check. The "verified" part was my own comparison.
- Neo4j was not running when checked. I did not start it (out of scope).
- Ollama was not touched.
