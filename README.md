<p align="center">
  <img src="assets/banner.svg" alt="Agent HUD" width="100%">
</p>

<p align="center">A local dashboard for your coding agents' skills, instructions, and plugin state.</p>

<p align="center"><b>English</b> | <a href="README.ko.md">한국어</a></p>

<p align="center">
  <img src="assets/screenshot.png" alt="Plugins &amp; skills tab: every skill with a badge per agent" width="640">
</p>

## Contents

- [The problem](#the-problem)
- [What it shows](#what-it-shows)
- [Concepts](#concepts)
- [Setting up groups](#setting-up-groups)
- [Install (macOS)](#install-macos)
- [Behavior across projects and sessions](#behavior-across-projects-and-sessions)
- [Managing the service](#managing-the-service)
- [Update checks](#update-checks)
- [Extend](#extend)
- [Feedback](#feedback)
- [Why it's built this way](#why-its-built-this-way)
- [License](#license)

## The problem

Different projects need different skills. Writing, app work and infrastructure
have almost nothing in common, but Claude Code loads every skill you installed
into every session regardless, because a skill's name and description go into
context at startup whether you use it or not.

Three plugins on this machine carried **60 skills** between them, plus commands
and hooks. At roughly 100 tokens of metadata per skill (the figure the
[Agent Skills spec](https://agentskills.io/specification) gives), that eats
**5,000–9,000 tokens in every session**, most of it on skills irrelevant to
whatever the project is.

You can turn plugins off, but the switch is one setting shared by every project,
so "on for this kind of work" and "on everywhere" are the same thing. Doing it by
hand at the start of each session gets old fast.

Agent HUD shows what each project actually loads, and lets you save the set you
use for that kind of work and apply it per project. It reads local files and
renders them; no accounts, no external services.

## What it shows

<p align="center">
  <img src="assets/screenshot-groups.png" alt="Groups tab" width="560">
  <img src="assets/screenshot-instructions.png" alt="Agent instructions tab" width="560">
</p>

Three tabs, one panel at a time.

- **Plugins & skills**: every skill on the machine, grouped by where it came from:
  each plugin, plus the ones that belong to no plugin. Each skill carries a badge
  per agent (Claude Code, Codex, Cursor, Copilot, Gemini CLI) showing which of them
  can actually see it in the selected project. Plugin on/off and skill blocking
  live here too, both per project and labelled Claude Code only, because no other
  agent has those concepts
- **Groups**: the plugins and skills you use together. Applying one to a project
  links its skills there, turns its plugins on and every other plugin off, in that
  project only
- **Agent instructions**: `CLAUDE.md`, `AGENTS.md`, `.clinerules`,
  `.cursor/rules/` and 25 other instruction files, with size and modified time, so
  you can see where they have drifted apart. Plus registered subagents

Dark mode by default (☀/☾ toggle) and an EN/한국어 toggle, both persisted to
`localStorage`.

## Concepts

These are Claude Code's own structure, not Agent HUD's, except where noted.

**Plugin**: an installable bundle of skills, agents, and commands, published to
a marketplace and installed with `claude plugin install`. Claude Code turns a
plugin on or off through `enabledPlugins` in a settings file. The plugin dot in
Agent HUD writes that into the project's `.claude/settings.local.json`, so it
applies to that project only, from the next session.

**Marketplace**: the source a plugin comes from, a git repo or a local path,
registered with `claude marketplace add`. Each plugin row shows its
marketplace's source path directly, so there's no separate marketplace list to
cross-reference. Agent HUD only displays this. It doesn't add or manage
marketplaces. Trusting a source is a deliberate, manual decision you make with
the `claude` CLI, not something a dashboard should do on your behalf.

**Skill**: a capability defined by a `SKILL.md` file, bundled inside a plugin.
Claude Code's plugin system enables or disables a whole plugin at once; it has
no separate "skill toggle." Individual skills are controlled a different way:
see permission override below. Click a plugin's name in Agent HUD to expand
its skill list, each with its description read from `SKILL.md`.

**Permission override**: a project-local `.claude/settings.json` entry under
`permissions.deny`, for example `"Skill(some-plugin:some-skill)"`. This is
Claude Code's actual mechanism for turning off one specific skill without
touching the rest of its plugin, and it's scoped to a single project rather
than the whole machine. The skill dot in Agent HUD writes this entry
directly, so blocking or allowing a skill applies immediately, unlike plugin
enable/disable.

**Group**: Agent HUD's own addition. Claude Code has no such concept. It's a
named set of plugins and skills you use together, for example "writing" versus
"video." Stored in `modes.json`. Edit the file directly, or manage it in the
Groups tab.

**Instructions (`CLAUDE.md`)**: global (`~/.claude/CLAUDE.md`) and per-project
(`<project>/CLAUDE.md`) markdown. Claude Code reads it as standing instructions
every session.

## Setting up groups

In the Groups tab, click "+ create a new group", give it a name, and pick which
plugin it starts with. Add more plugins and skills from the group's own row.
Then pick a project and click "Apply to this project": the group's skills get
linked into that project, its plugins turn on and every other plugin turns off,
in that project only. Plugin changes take effect from the next session.

The same from a terminal:

```bash
python3 ~/.claude/tools/agent-hud/server.py groups          # list groups
python3 ~/.claude/tools/agent-hud/server.py apply dev       # apply "dev" to the current folder
python3 ~/.claude/tools/agent-hud/server.py apply --off     # stop using a group here
```

You can also edit `modes.json` directly. A plain list means plugins only:

```json
{
  "dev": {
    "plugins": ["some-plugin@some-marketplace"],
    "skills": ["some-skill"]
  },
  "video": ["video-tools@local"]
}
```

Plugin names have to match what shows up in the Plugins & skills tab exactly,
including the `@marketplace` part. Skill names are the skill's folder name. The
dashboard picks the file up on its next poll, no restart needed.

## Install (macOS)

```bash
git clone https://github.com/ganggangstone/agent-hud.git agent-hud && cd agent-hud
./install.sh
```

The installer copies `server.py` to `~/.claude/tools/agent-hud/`, seeds
`modes.json` from the example, and registers a `launchd` service. From then on
the dashboard keeps running independently of any terminal or Claude Code
session, and restarts automatically if it dies.

It prints, but does not apply, a hook snippet for `~/.claude/settings.json` so
each Claude Code session registers its project directory with the dashboard.
Merge it in by hand. The installer won't touch a settings file that may
already hold hooks of your own.

This packaging needs `launchd`, so it's macOS-only. `server.py` itself has no
OS-specific code. On Linux, point a `systemd --user` unit's `ExecStart` at it
instead of running `install.sh`.

## Behavior across projects and sessions

One server process serves every project on the machine. When a session
starts, its hook checks whether a server is already running. If one is, it
just registers the current project path. It starts a new one only if none is
running. The server doesn't start or stop, and its port doesn't change, just
because you open or close a terminal in the same project. With two or more known
projects, the relevant panels show a dropdown to switch between them.

## Managing the service

```bash
launchctl list | grep agent-hud                               # status
launchctl kickstart -k gui/$(id -u)/com.agent-hud             # restart after editing server.py
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.agent-hud.plist  # stop
tail -f ~/.claude/tools/agent-hud/launchd.err.log             # logs
```

Setting `CLAUDE_HUD_DISABLE=1` before a session's hook runs skips starting a
new server. It has no effect on one already running.

## Update checks

The dashboard checks GitHub Releases for a newer tag every 12 hours, in a
background thread, and shows a banner when one exists. It never downloads or
installs anything. You update by running `git pull` in your clone and
restarting the service.

## Extend

New panel: write `def collect_x(ctx) -> dict` and add it to `PANELS`.

## Feedback

Bug reports and suggestions go to [Issues](../../issues). The dashboard's
"report an issue" link opens a short form with the version already filled in.
Write in English or Korean, whichever is easier.

## Why it's built this way

Decisions with real alternatives (the single-file/no-dependency choice, how
plugin and skill state is read and written, why polling instead of websockets)
are recorded in [docs/ADR.md](docs/ADR.md).

## License

MIT. See [LICENSE](LICENSE).
