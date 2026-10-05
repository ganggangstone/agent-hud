# Contributing

## Run it from the checkout

`dev` is the development branch; `main` is the distribution branch. Make changes in a
separate worktree, run the checks, and push to `dev`. Both branches run CI. Merge verified
changes into `main` before creating a release tag: the release workflow rejects commits
that are not in `main`. A push to `dev` alone does not create a release.

```bash
python3 server.py
```

It serves on `127.0.0.1:41717` and reads local files only. If the installed
dashboard is already running, a checkout started with `python3 server.py` just hands
over to it and exits; run it as `AGENT_HUD_PORT=41718 python3 server.py` to try your
changes side by side. `install.sh` copies
`server.py` into `~/.claude/tools/agent-hud/` and registers a launchd service;
that copy is a build artifact. **Edit the checkout, never the installed copy** —
a copy you can edit while it runs will quietly get ahead of the source.

After changing `server.py`:

```bash
cp server.py ~/.claude/tools/agent-hud/server.py
launchctl kickstart -k gui/$(id -u)/com.agent-hud
```

## Checks

```bash
for t in tests/test_*.py; do python3 "$t" || echo "FAIL $t"; done
```

No framework, no dependencies — each file runs on its own and asserts.

GitHub Actions runs the same loop on every push and pull request
(`.github/workflows/test.yml`), so a pull request tells you whether the checks pass
without you running them. `node` is the only thing beyond Python that the checks need,
for the `--check` passes over inline `<script>` blocks.

Pushing a `v*` tag triggers `.github/workflows/release.yml`: it verifies that the commit
is in `main`, refuses to publish when the tag and `VERSION` in `server.py` disagree,
runs the checks, and creates the release.
The dashboard's update notice reads `releases/latest`, so a tag without a release does
nothing for users.

- **`tests/test_page_js.py`** runs `node --check` over every `<script>` block in the
  page. The UI is one Python string, so a stray quote makes the server answer
  200, render the header, and draw nothing else. Nothing else catches that.
- **`tests/test_instructions.py`** — instruction-file discovery: depth, pruning, the
  scan budget.
- **`tests/test_link_skill.py`** — linking a skill must create only symlinks and
  remove only symlinks. A real directory a user placed is never touched.
- **`tests/test_sets.py`** — group format compatibility, switching groups, leaving
  links the user made by hand alone.
- **`tests/test_plugin_scope.py`** — plugin state is per project. The user-wide
  settings file must come out byte-identical.
- **`tests/test_stale_deny_cleanup.py`** — removes the no-op `Skill(plugin@marketplace:skill)`
  deny entries older versions wrote, from both project settings files, keeping every
  other rule and key and leaving files with nothing to remove untouched.
- **`tests/test_skill_roots_agy.py`** — Antigravity (agy) is in the agent list and reads
  `~/.gemini/config/skills` and project `.agents/skills`, not `~/.agents/skills`.
- **`tests/test_cli.py`** — the `groups` and `apply` subcommands, run as a
  subprocess against a throwaway home.
- **`tests/test_data_dir.py`** — data files sit next to `server.py` by default
  and move with `AGENT_HUD_HOME`.
- **`tests/test_loaded.py`** — the count of skills a project loads.
- **`tests/test_skill_spec.py`** — detection of skills that break the Agent
  Skills spec.
- **`tests/test_subprojects.py`** — subfolders that are projects of their own
  show up in the folder picker.
- **`tests/test_update_hint.py`** — the request a cloned install copies for its
  AI agent points at a README section that exists and gives both update paths
  (`git pull` then `install.sh`, or `brew upgrade`), and the Homebrew check
  (`brew_prefix`) tells a Homebrew install from a clone or another formula.
- **`tests/test_install_app.py`** — `/manifest.json` and `/icon.png` are valid
  and the page actually links the manifest. Whether Chrome offers the install
  prompt for real can only be checked in a browser.
- **`tests/test_mac_app.py`** — `packaging/Agent HUD.app` has a valid `Info.plist`,
  its launcher is executable and runs `agent-hud open`, and the icon it names exists. The
  `agent-hud-app` cask in the tap installs this folder from the release tarball.
- **`tests/test_project_skill_source.py`** — a skill that lives only inside a registered
  project can be a group source, links are never taken as sources, plugin and user skills
  win name clashes, and the source project's real folder is left alone.
- **`tests/test_projects_race.py`** — sessions registering at the same moment neither corrupt
  the project list nor drop entries from it.
- **`tests/test_port_owner.py`** — when another program answers on the dashboard's
  port, the dashboard does not treat it as already running.

If you add a check, **break the thing it checks and watch it fail.** A check
that has never failed is a check nobody has verified.

### Strings

The UI ships two dictionaries, `en` and `ko`. After editing either, run:

```bash
python3 - <<'PY'
import re; s=open('server.py',encoding='utf-8').read()
used=set(re.findall(r"t\(\)\.([a-z_0-9]+)",s))
def keys(n):
    b=s[s.index(f"  {n}: {{"):]; b=b[:b.index("\n  },")]
    return set(re.findall(r"(?:^|,)\s*([a-z_0-9]+):",b,re.M))-{n}
en,ko=keys("en"),keys("ko"); skip={"title_groups","title_skills","title_instructions",
 "agents","mcp","commands","hooks","lsp","monitors","bin","settings"}
print("en/ko:", "match" if en==ko else sorted(en^ko))
print("missing:", sorted(used-en-skip) or "none", "| unused:", sorted(en-used-skip) or "none")
PY
```

Several strings share a line. Delete a key by name, not by line, or you will
take its neighbour with it.

## Command line

```
agent-hud                      start the dashboard
agent-hud open                 open it in the browser, starting it first if needed
agent-hud groups               list groups, and which one this folder uses
agent-hud apply <group> [dir]  apply a group to a folder (default: cwd)
agent-hud apply --off [dir]    stop using one here
agent-hud worktrees [dir]      list related worktrees and skill file states
agent-hud worktrees apply [dir] add saved skills before starting an agent
```

`apply` calls the same `assign_set()` the dashboard does and needs no running
server, so it works in a setup script. Running from the checkout, prefix it
with `AGENT_HUD_HOME=~/.claude/tools/agent-hud` to act on the installed data.

## Where its data lives

`projects.json`, `modes.json`, `project-sets.json` and `worktree-skills.json` sit next to
`server.py` by default. Set `AGENT_HUD_HOME` to put them somewhere else — the
Homebrew formula does exactly that, because a package manager replaces the code
directory on every upgrade and would take your groups with it.

`worktree-skills.json` stores repository defaults, per-worktree exclusions/custom
selections, application results and the links created by this feature. It is personal
state, ignored by Git. A file lock also coordinates the background worker, HTTP requests
and the pre-launch CLI across processes. Automatic application uses the same additive
writer as manual application; no worktree settings or existing entries are deleted.

`tests/test_worktrees.py` uses temporary repositories and linked worktrees, actual HTTP
requests and CLI subprocesses. It covers identity, conflicts, symlinked parents, deletion,
opt-in discovery, exclusions and custom skill sources. It does not establish live agent
skill discovery. `tests/test_release_branch.py` executes the release branch guard against
temporary Git history, proving an unmerged development commit is rejected and a main
commit is allowed.

## Adding a panel

Write `collect_x(ctx) -> dict` and add it to `PANELS`. The dict is handed to
the browser as JSON and rendered by the branch that matches its shape.

## Conventions the screen follows

- **A pill is a control you can press. A dot is a fact you cannot.** No
  exceptions — a dot that toggles, or a pill that does not, breaks every other
  row's meaning.
- **No Korean particles on interpolated names.** Plugin and skill names are
  mostly Latin, so `${n}은/는` picks the wrong one roughly half the time. Write
  `` `${n} — explanation` `` instead.
- **Korean word order for counts**: `스킬 43개`, not `43개 스킬`.
- **Never truncate silently.** When the instruction scan hits its budget, the
  panel says so. A quiet cap reads as "that was all of them".
- Screenshots are taken from a throwaway instance serving fake data, never from
  a real one.

## Scope

Plugins are a Claude Code concept; this dashboard reads Claude Code's copies of
them. Groups are Agent HUD's own. Skills and instruction
files are read for every supported agent. Don't invent equivalents for tools that have none — say
which agent a control applies to instead.
