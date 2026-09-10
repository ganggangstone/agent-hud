# Contributing

## Run it from the checkout

```bash
python3 server.py
```

It serves on `127.0.0.1:7717` and reads local files only. `install.sh` copies
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
python3 test_page_js.py && python3 test_instructions.py && \
python3 test_link_skill.py && python3 test_sets.py && python3 test_plugin_scope.py
```

No framework, no dependencies — each file runs on its own and asserts.

- **`test_page_js.py`** runs `node --check` over every `<script>` block in the
  page. The UI is one Python string, so a stray quote makes the server answer
  200, render the header, and draw nothing else. Nothing else catches that.
- **`test_instructions.py`** — instruction-file discovery: depth, pruning, the
  scan budget.
- **`test_link_skill.py`** — linking a skill must create only symlinks and
  remove only symlinks. A real directory a user placed is never touched.
- **`test_sets.py`** — group format compatibility, switching groups, leaving
  links the user made by hand alone.
- **`test_plugin_scope.py`** — plugin state is per project. The user-wide
  settings file must come out byte-identical.

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
- Screenshots for the README are taken from a throwaway instance serving fake
  data — never from a real one. See `assets/screenshot-source.html`.

## Scope

Plugins, groups and per-skill blocking are Claude Code concepts; this dashboard
reads Claude Code's copies of them. Skills and instruction files are read for
every supported agent. Don't invent equivalents for tools that have none — say
which agent a control applies to instead.
