# What works and what does not in Agent HUD

For people using Agent HUD, and for agents operating it on someone's behalf. Based on v0.6.3. [한국어](GUIDE.ko.md)

Evidence labels: **[measured]** run directly, **[docs]** official documentation, **[unverified]** not confirmed.

## Start here

HUD can switch things on and off **only for Claude Code**. For other agents it only adds or removes skill links in the project folder.

- **Switches** (Always, Only when you type /name, Excluded) write Claude Code's `skillOverrides` only.
- **Groups** switch Claude Code plugins and skills, and place skill links in `.claude/skills` and `.agents/skills`.
- **Header numbers** are computed by HUD. They are not a measurement of what a session actually loaded.
- Switch and plugin changes apply **from the next session**.

## By agent

| Agent | Turn a skill off from HUD | Add a skill with a group link | Instruction totals |
|---|---|---|---|
| Claude Code | Yes [measured] | Yes [measured] | Yes, including parent folders, `.claude/CLAUDE.md`, rules, the `AGENTS.md` fallback, `claudeMdExcludes` and `@` imports [measured] |
| Codex | No. Skills it disabled itself are read and shown | Yes (`.agents/skills`) [docs] | Partial. Counted per folder from the Git root [docs]. Size limit and fallback file names are not applied ([#23](../../../issues/23)) |
| Gemini CLI | No. Skills it disabled itself are read and shown | Yes (`.agents/skills`) [docs] | Partial. Global and root `GEMINI.md` only, `@` imports not followed |
| Antigravity | No | Yes (`.agents/skills`) [docs] | Yes. Instructions in the start folder and `always_on` rules [measured], global instructions and rules [docs] |
| Cursor | No | Yes, but it also reads global folders, so it cannot be split per project [docs] | Partial. Root `AGENTS.md` only [unverified: rule file totals, [#35](../../../issues/35)] |
| Copilot | No | Yes, but it also reads global folders, so it cannot be split per project [docs] | Partial. `.github/copilot-instructions.md` and root `AGENTS.md` only [unverified: [#35](../../../issues/35)] |

## Common mistakes

| What you try | What happens | Do this instead |
|---|---|---|
| Turn off a Codex skill with a switch | It stays on | Change that tool's own settings, or remove the project link |
| Turn off Codex instructions with `claudeMdExcludes` | Codex does not read this setting | Adjust Codex's own file layout |
| Turn off one skill inside a plugin | Not possible. `permissions.deny` does not reduce tokens either [measured] | Turn off the whole plugin |
| Tick "let other agents use it" when `.agents/skills` is a linked folder | The write is blocked, as a safeguard [measured] | Use a real folder with per-skill links |
| Keep different skills with the same name in `.claude` and `.agents` | They show as separate rows, but each tool reads different content | Use different names |
| Create a project skill named like a global skill | Claude Code uses the global skill first [docs] | Use a different name |

## For agents

The HUD server is at `http://127.0.0.1:41717`. If it is not running, tell the user instead of starting it yourself.

**Read-only**

```bash
curl -s "http://127.0.0.1:41717/api/state?project=<absolute path>"   # all panels as JSON
agent-hud groups                                                      # list groups
agent-hud worktrees [folder]                                          # skill state across worktrees
agent-hud --help                                                      # usage
agent-hud --version                                                   # version
```

**Changes files: only when the user asks**

```bash
agent-hud apply <group> [folder]    # changes skill links and .claude/settings.local.json
agent-hud apply --off [folder]      # removes group skill links and restores plugin and skill settings
agent-hud worktrees apply [folder]  # adds the saved skill set
```

**Do not**

- Run `agent-hud` without arguments just to check something. It starts the server and does not return in the foreground.
- Change settings through `POST /api/*`. These are internal routes for the page and may change.
- Edit `modes.json` or `settings.local.json` first when one of the commands above does the job.
- Use the real data folder for experiments. Separate it with `AGENT_HUD_HOME` and `AGENT_HUD_PORT`.

**After a change**

1. Read the project's values again from `/api/state`.
2. Tell the user that switch and plugin changes need a new session.
3. If the real effect matters, check with `/context` inside Claude Code.

## Updating

```bash
brew update && brew upgrade agent-hud && brew services restart agent-hud
```

Without `brew update` the tap stays old and the new version is not found [measured]. The update notice checks once a day, so it can lag right after a release.

## Not confirmed yet

Behaviour that still needs measuring is collected in [#35](../../../issues/35). If anything here differs from what you see, please open an issue.
