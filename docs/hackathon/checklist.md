# Kiroween 2026 submission checklist

Deadline: **Friday, December 4, 2026, 2:00 PM Pacific** ([kiroween.devpost.com](https://kiroween.devpost.com/)). Checked on 2026-11-16.

## Required

| # | Requirement | State | Proof |
|---|---|---|---|
| 1 | Public GitHub repo | done | `gh repo view` shows `PUBLIC`: [github.com/manvendersingh21/tremor-core](https://github.com/manvendersingh21/tremor-core) |
| 2 | Open source license, visible | done | `LICENSE` (MIT) at the root; GitHub shows "MIT License" |
| 3 | `/.kiro` at the root, not ignored | done | `git ls-files .kiro` lists 45 files; `git check-ignore` finds no rule for `.kiro/` |
| 4 | Built in the window | done | first commit 6177579 on 2026-11-13 |
| 5 | Working app URL | **partial** | [manvendersingh21.github.io/tremor-core](https://manvendersingh21.github.io/tremor-core/) answers (HTTP 200) but is a static view. The live app runs only at `127.0.0.1:8765` (`make web`). |
| 6 | Text description | drafted | `docs/hackathon/submission.md`, "Devpost text description" |
| 7 | Public YouTube demo under 3 minutes | **not done** | script ready: `docs/hackathon/demo_script.md` (2:45) |
| 8 | Write-up on how Kiro was used | drafted | `docs/hackathon/submission.md`, "How we used Kiro" |
| 9 | Category | chosen: Frankenstein (second: Costume Contest) | `docs/hackathon/submission.md`, "Why Frankenstein" |

## Bonus prizes

| Prize | What it needs | State | Proof |
|---|---|---|---|
| Best Kiro Crew App | built with Kiro Crew; tick the box on the form | ready to tick | `docs/hackathon/submission.md`, "Kiro Crew" section; `bench/results_backend_v2.md` |
| Best Demo | a strong video | needs the video | `docs/hackathon/demo_script.md` |
| Bonus Blog | public post on a third-party blog site that says it is for Kiroween 2026 | draft ready, not posted | `docs/hackathon/blog_post.md` (about 890 words) |
| Social Blitz | a public post that starts with `#KiroweenHackathon26` | drafts ready, not posted | `docs/hackathon/social_post.md` (3 versions) |

## Judging and our answer

| Criterion | Our answer | Proof |
|---|---|---|
| Potential impact | 62% to 87% a month saved vs GPT-5.5 with 30% repeats; no saving vs the 763B at 100k a day | `bench/results_company_cost.md` |
| Technological implementation (Kiro depth) | 7 steering files, 7 specs, 6 hooks, 4 agents, MCP server, Power, 41 property tests, 5 junior PRs | `docs/hackathon/submission.md` |
| Design | painted walk-in castle, Halloween dashboard, 57.8 to 60 fps | `site/docs/ui_polish.md` |
| Innovation | test-gated bank and cache, cost per call, same-box vs two-box spec decoding | `bench/results_spec_modal.md`, `bench/results_bank.md` |
| Presentation | 2:45 video, losses shown next to wins | `docs/hackathon/demo_script.md` |

## Steps only the owner can do

1. **Record the video.** Follow `docs/hackathon/demo_script.md`. Hide `.env`, shell history and any host, IP, port or key path.
2. **Upload to YouTube as Public** (not Unlisted, not Private). Keep it under 3:00. Put "Kiroween 2026" in the title.
3. **Pick the working app URL.** Either keep the Pages static view, or ask for a hosted live demo with a demo tenant and no private hosts. The live demo would spend money on hosting and model calls, so it needs your yes.
4. **Fill the Devpost form.** Paste the pitch and the description from `docs/hackathon/submission.md`. Add the repo URL, the app URL and the YouTube URL. Pick Frankenstein.
5. **Tick the bonus boxes** on the form: Best Kiro Crew App and Best Demo, if the form offers them.
6. **Post the blog** on a third-party site (for example dev.to, Medium or Hashnode). Keep the line that says it is for Kiroween 2026. Paste the post URL in the form.
7. **Post on social.** Use one version from `docs/hackathon/social_post.md`. It must start with `#KiroweenHackathon26`. Paste the post URL in the form.
8. **LinkedIn, startup or student fields:** fill them only if they are true for you. Leave them empty otherwise.
9. **Confirm the Kiro surfaces.** The write-up says Kiro Crew and `kiro-cli` were used, the IDE hooks were run by hand, and Kiro Web was not used. Correct it if you used the IDE or Web.
10. **Submit before Friday, December 4, 2:00 PM Pacific.** Aim for December 3.

## Open items the team can do

| Item | Why | Owner |
|---|---|---|
| Commit `.kiro/settings/mcp.json` after a secret scan, or point judges to `powers/chimera/workspace-mcp.json` | it is untracked today | frontend |
| Tick `tasks.md` in `.kiro/specs/savings-replay/` and `.kiro/specs/lora-distill/` | both are built and measured, 0 boxes ticked | frontend |
| Check the Kiro handle in `docs/hackathon/social_post.md` | `@kirodotdev` is not confirmed | owner |
| Read the full rules page once | Devpost blocked direct fetches earlier; the facts here came from the brief | owner |
