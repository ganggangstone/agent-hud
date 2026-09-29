<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/English-selected-2ea44f?style=for-the-badge" alt="English"></a>
  <a href="README.ko.md"><img src="https://img.shields.io/badge/%ED%95%9C%EA%B5%AD%EC%96%B4-%EC%9D%BD%EA%B8%B0-555?style=for-the-badge" alt="한국어"></a>
</p>

<p align="center"><b>한국어 설명은 위의 <a href="README.ko.md">한국어</a> 버튼을 누르세요.</b></p>

<p align="center">
  <img src="docs/images/banner.svg" alt="Agent HUD" width="100%">
</p>

<p align="center">A local dashboard for your coding agents' skills, instructions, and plugin state.</p>

<p align="center">
  <a href="https://ganggangstone.github.io/agent-hud/">Website</a> ·
  <a href="../../releases">Releases</a> ·
  <a href="../../issues">Issues</a>
</p>

<p align="center">
  <img src="docs/images/demo.gif" alt="Applying the app group to a project takes it from 60 skills (about 6,000 tokens) to 6" width="880">
</p>

Coding agents such as Claude Code, Codex and Cursor put the name and description of every
installed skill into the context at the start of each session, including skills that
session never uses. On the author's machine, 60 skills came to 5,000–9,000 tokens per
session. `claude plugin disable <plugin> -s local` turns a plugin off for one project, but only
one plugin at a time, and nothing shows how many skills are still loaded.

Agent HUD shows how many skills each project loads, and lets you save the plugins and
skills you use together as a group and apply a different group to each project.

## Quickstart (macOS)

If you use an AI coding agent, it can do the whole install for you. Paste this into
Claude Code, Codex, or whichever agent you use:

> Install Agent HUD from https://github.com/ganggangstone/agent-hud. Follow the "For AI agents" section of its README.

To do it yourself:

1. Install it with Homebrew. This puts an Agent HUD app in Applications and installs the
   `agent-hud` command.

   ```bash
   brew install --cask ganggangstone/tap/agent-hud-app
   ```

2. Open **Agent HUD** from Launchpad or Applications. The dashboard opens in your browser at
   <http://127.0.0.1:41717>. Add the project folder you work in with "+ add a folder" in the
   sidebar. If you use Claude Code, paste the hook setting the installer prints into
   `~/.claude/settings.json` and you can skip this: each folder you open a session in is
   added for you. Agent HUD does not search your disk for projects. The sidebar lists only
   folders added one of these two ways, so projects you opened before adding the hook need
   "+ add a folder" once.
3. In the Groups tab, create a group and click "Apply to this project".

## Install

The command above installs two Homebrew packages: the `agent-hud` formula (the dashboard
and its command) and the `agent-hud-app` cask (an app icon that runs `agent-hud open`).
If you only want the command:

```bash
brew install ganggangstone/tap/agent-hud
brew services start agent-hud
```

Without Homebrew, clone the repository and run the install script:

```bash
git clone https://github.com/ganggangstone/agent-hud.git agent-hud && cd agent-hud
./install.sh
```

The install script copies `server.py` to `~/.claude/tools/agent-hud/`, creates
`modes.json` from the example file, and registers a `launchd` service, so the dashboard
keeps running after you close terminals and restarts if the process exits. Homebrew
installs an `agent-hud` command and runs the same server with `brew services`.

## For AI agents

Steps for an agent asked to install, open, or update Agent HUD on the user's Mac.

1. **Install.** If `brew` is available, run
   `brew install --cask ganggangstone/tap/agent-hud-app && brew services start agent-hud`.
   The first installs the dashboard, its command and an app icon; the second keeps it running
   from login and opens it in the browser. Otherwise clone this repository (for example to `~/agent-hud`) and run `./install.sh` in it.
2. **Register sessions (Claude Code only).** Add a `SessionStart` hook to
   `~/.claude/settings.json`. Merge it into any hooks already there; do not replace them.
   The command is `nohup agent-hud --register "$PWD" >/dev/null 2>&1 & disown` for a Homebrew
   install, or `nohup python3 "$HOME/.claude/tools/agent-hud/server.py" --register "$PWD" >/dev/null 2>&1 & disown`
   for a cloned one.
3. **Open.** `agent-hud open` for a Homebrew install, or `open http://127.0.0.1:41717`.
   With the cask installed, tell the user they can reopen it any time from **Agent HUD** in
   Launchpad.
4. **Update.** Follow [Updating](#updating). For a cloned install you need the clone's folder;
   if you did not install it yourself, ask the user where it is. Tell the user which version
   was installed before and after.

## What it shows

<p align="center">
  <img src="docs/images/groups.png" alt="Groups tab" width="560">
  <img src="docs/images/skills.png" alt="Plugins &amp; skills tab: every skill with a badge per agent" width="560">
  <img src="docs/images/instructions.png" alt="Agent instructions tab" width="560">
</p>

- **Groups**: lists of plugins and skills you use together. Applying a group to a project
  links the group's skills into that project's skill folders and turns on its plugins and
  skills. Every other plugin, and every skill outside a plugin, is turned off for Claude
  Code. Other projects are not changed.
- **Plugins & skills**: every installed skill, listed by plugin, with a badge for each
  agent that can read it in the selected project. Plugins, and skills that aren't part of
  a plugin, have an ON/OFF switch for Claude Code.
- **Agent instructions**: 30 kinds of instruction files in the project, such as
  `CLAUDE.md`, `AGENTS.md` and `.cursor/rules/`, with their size and modified time.
  You can see at a glance that `CLAUDE.md` was updated but `AGENTS.md` wasn't.

## Concepts

| Concept | Belongs to |
|---|---|
| [Skill](#skill) | Every agent that follows the Agent Skills standard |
| [Instruction file](#instruction-file) | Each agent, with its own file name |
| [Plugin](#plugin) | Claude Code |
| [Group](#group) | Agent HUD |

### Skill

A folder with a `SKILL.md` file, following the [Agent Skills](https://agentskills.io)
standard. The six agents read the same format but look in different folders: in a
project, Claude Code reads `.claude/skills/`, Codex, Gemini CLI and Antigravity read
`.agents/skills/`, and Cursor and Copilot read both. Agent HUD links the skill into both
folders instead of copying it, so an agent reads the same copy whichever folder it looks in.
Following the link was checked with Claude Code, Codex, Gemini CLI, Copilot and Antigravity,
not yet with Cursor.

A skill that isn't part of a plugin, whether in `~/.claude/skills/` or in the project, can
be switched off per project. Agent HUD writes `skillOverrides` into the project's
`.claude/settings.local.json`, which only Claude Code reads.

A skill inside a plugin is read only by Claude Code, while that plugin is on. The checkbox
on the Plugins & skills tab links it into the project's skill folders, so the other agents
read it too, and Claude Code reads it even with the plugin off.

### Instruction file

A markdown rules file an agent reads every session: `CLAUDE.md` for Claude Code,
`AGENTS.md` for Codex, Cursor and others, `.cursor/rules/` for Cursor,
`.github/copilot-instructions.md` for Copilot. Agent HUD lists these files and never
edits them.

### Plugin

A bundle of skills, subagents, commands and hooks, installed with
`claude plugin install`. The ON/OFF switch in Agent HUD writes `enabledPlugins` into the
selected project's `.claude/settings.local.json`, so other projects are not affected.

### Group

A named list of plugins and skills you use together, such as "writing" or "video
editing". Groups exist only in Agent HUD and are stored in `modes.json`.

A group can hold plugin skills, skills in your user skill folders (`~/.claude/skills`,
`~/.agents/skills` and so on), and skills that live inside one of the projects in the
sidebar. For the last kind, other projects get a link to that project's folder, so moving or
deleting that project breaks the link. When two skills share a name, a plugin skill wins
over a user skill, and a user skill over a project one.

## Setting up groups

1. In the Groups tab, click "+ create a new group".
2. Enter a name and choose the first plugin to add.
3. Add more plugins and skills from "+ add a plugin or skill…" under the group.
4. Pick a project in the sidebar, then click "Apply to this project" in the Groups tab.

### Which agents it applies to

Every agent gets to read the group's skills. Switching off what isn't in the group applies
to Claude Code only, because the other agents have no per-project setting for turning a
skill off.

| | In the group | Not in the group |
|---|---|---|
| Claude Code | On | Plugins and skills outside a plugin are turned off |
| Codex, Gemini CLI, Antigravity, Cursor, Copilot | Skills are read | Not turned off |

If you use more than one agent, keep your skills in `~/.claude/skills` and link them with
groups. Codex, Gemini CLI and Antigravity then read a skill only in the projects a group
linked it into, and Claude Code can switch it per project. A skill in `~/.agents/skills` is
read by Codex and Gemini CLI in every project. Cursor and Copilot read both folders
everywhere, so they can't be split per project.

The same from a terminal (`agent-hud` instead of `python3 …/server.py` if you installed
with Homebrew):

```bash
python3 ~/.claude/tools/agent-hud/server.py groups          # list groups
python3 ~/.claude/tools/agent-hud/server.py apply dev       # apply "dev" to the current folder
python3 ~/.claude/tools/agent-hud/server.py apply --off     # remove the group's skill links (plugin on/off stays)
```

You can also edit `modes.json` directly. A value written as a single list is a group with
plugins only.

```json
{
  "dev": {
    "plugins": ["some-plugin@some-marketplace"],
    "skills": ["some-skill"]
  },
  "video": ["video-tools@local"]
}
```

Plugin names must match the names on the Plugins & skills tab, including the
`@marketplace` part. A skill name is the skill's folder name. The dashboard picks up the
saved file on its next refresh, so you don't need to restart anything.

## Behavior across projects and sessions

One server runs on the computer and every project uses it. Opening or closing terminals
does not restart the server or change its port.

## Managing the service

```bash
launchctl list | grep agent-hud                               # check it is running
launchctl kickstart -k gui/$(id -u)/com.agent-hud             # restart
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.agent-hud.plist  # stop until next login
tail -f ~/.claude/tools/agent-hud/launchd.err.log             # view logs
```

With Homebrew, use `brew services restart agent-hud` and `brew services stop agent-hud`;
logs are in `$(brew --prefix)/var/log/agent-hud.err.log`. `agent-hud open` opens the
dashboard in your browser, starting it first if it is not running.

The dashboard always uses port 41717, so bookmarks and the installed app keep working. If
another program already uses that port, the dashboard waits for it to be free instead of
moving to another number, and says so in the log.

If `CLAUDE_HUD_DISABLE=1` is set before a session's hook runs, that session neither starts
a server nor registers its project, and `groups` and `apply` do nothing. A server that is
already running keeps running.

## Open it as an app

Click **Install app** in the header to get a window without browser chrome and with its
own icon. Chrome and Edge install it in one step. In other browsers,
including Safari, it tells you which menu to use instead (Safari on macOS Sonoma or later: File → Add to Dock).

## Updating

Once a day the dashboard checks GitHub Releases for a new version and shows a notice at
the top of the page when there is one.

- **Homebrew:** click **Update now** in the notice. The dashboard runs `brew update` and
  `brew upgrade agent-hud`, restarts itself on the new code, and the page reloads. From a
  terminal: `brew update && brew upgrade agent-hud && brew services restart agent-hud`.
- **Cloned:** click **Copy a request for your AI agent** and paste it into your agent, or
  run `git pull` in the clone and then `./install.sh`. The service runs the copy in
  `~/.claude/tools/agent-hud/`, so `git pull` alone changes nothing; `./install.sh` copies
  the new file and restarts the service.

The daily check is the only request the dashboard makes on its own. It downloads an update
only when you click **Update now**, and Homebrew does the downloading. Agent HUD reads and
writes settings files on this computer only and needs no account.

## Known limitations

- **macOS only.** The installer relies on `launchd`. `server.py` has no macOS-only code,
  so on Linux you can run it from a `systemd --user` unit instead. Windows is not
  supported yet ([#1](../../issues/1)).
- **Plugin changes take effect from the next session.** Claude Code reads plugin state
  when a session starts.
- **You can't hide one skill of a plugin.** A `permissions.deny` entry stops the skill
  from being invoked, but its name and description still load every session, so it
  saves no tokens ([docs/ADR.md](docs/ADR.md) section 10). Turning the whole plugin off
  is the only way.

## Feedback and contributing

Report bugs and suggestions in [Issues](../../issues), in English or Korean. The "send
feedback ↗" link at the bottom of the dashboard opens an issue form with the version
already filled in. To run it from a checkout, run the checks, or add a panel, see
[CONTRIBUTING.md](CONTRIBUTING.md). Design decisions and the alternatives behind them
are in [docs/ADR.md](docs/ADR.md).

## License

MIT. See [LICENSE](LICENSE).
