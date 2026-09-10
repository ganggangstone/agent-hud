#!/usr/bin/env python3
"""Agent HUD: live status dashboard for a local Claude Code setup.

Extensibility: add a new panel by writing one function of shape
    def collect_x(ctx) -> dict   and appending it to PANELS.
Add a new plugin group by editing modes.json, or via the "+" button in the
dashboard UI itself — no code change needed either way.
"""
import json, os, socket, http.server, socketserver, threading, webbrowser, sys, time, subprocess, shutil, resource

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
PORT_FILE = os.path.join(TOOL_DIR, ".port")
PROJECTS_FILE = os.path.join(TOOL_DIR, "projects.json")
MODES_FILE = os.path.join(TOOL_DIR, "modes.json")
CLAUDE_BIN = shutil.which("claude") or "/opt/homebrew/bin/claude"
PROJECT_DIR = os.getcwd()  # fallback: cwd of whichever invocation started this process

VERSION = "0.1.0"
# TODO: 실제로 push하는 저장소로 확정되면 이 값을 바꾼다.
UPDATE_REPO = "ganggangstone/agent-hud"
UPDATE_CACHE_FILE = os.path.join(TOOL_DIR, ".update_check.json")
UPDATE_CHECK_INTERVAL_SEC = 12 * 60 * 60


def register_project(path):
    """Record a project dir as 'seen' so the dashboard can offer it in the project dropdown."""
    if path in ("/", HOME):
        return  # server's own cwd under launchd, not a real project
    projects = read_json(PROJECTS_FILE, {})
    projects[path] = time.time()
    try:
        with open(PROJECTS_FILE, "w") as f:
            json.dump(projects, f)
    except Exception:
        pass


def known_projects():
    # 지워진 디렉터리는 뺀다. 남겨두면 대시보드가 없는 폴더를 기본 선택해 빈 화면을 보인다.
    projects = read_json(PROJECTS_FILE, {})
    return sorted((p for p in projects if p not in ("/", HOME) and os.path.isdir(p)),
                  key=lambda p: -projects[p])


def default_project_dir(ctx):
    """The project a panel should assume when the browser hasn't picked one.
    Falls back to the most recently seen project rather than the server's own
    cwd (which is "/" when launchd starts it), so the UI never shows a bare
    "/" as if that meant something.
    """
    explicit = ctx.get("project_dir")
    if explicit:
        return explicit
    known = known_projects()
    return known[0] if known else PROJECT_DIR


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


# 버전 확인만 하고 다운로드는 사용자가 직접 한다. git으로 받는 도구라 업데이트 경로가
# 이미 있고(git pull), 실행 중인 서버가 자기 코드를 덮어쓰는 구조를 만들 이유가 없다.
# 근거는 docs/ADR.md 7번.
def _fetch_latest_release():
    import urllib.request
    req = urllib.request.Request(
        f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "agent-hud"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
    return (data.get("tag_name") or "").lstrip("v") or None


def _update_check_loop():
    # 항상 백그라운드 스레드에서만 돈다 — /api/state 요청 경로는 절대 네트워크를 기다리지 않는다.
    while True:
        try:
            latest = _fetch_latest_release()
            if latest:
                with open(UPDATE_CACHE_FILE, "w") as f:
                    json.dump({"latest": latest, "checked_at": time.time()}, f)
        except Exception:
            pass  # 저장소가 아직 비공개거나 오프라인이면 조용히 넘어간다 — 대시보드 본 기능과 무관
        time.sleep(UPDATE_CHECK_INTERVAL_SEC)


def collect_update(ctx):
    cached = read_json(UPDATE_CACHE_FILE, {})
    latest = cached.get("latest")
    return {
        "panel": "update",
        "version": VERSION,
        "latest": latest,
        "has_update": bool(latest) and latest != VERSION,
        "repo": UPDATE_REPO,
    }


def collect_groups(ctx):
    project_dir = default_project_dir(ctx)
    modes = read_json(MODES_FILE)
    settings = read_json(os.path.join(CLAUDE_DIR, "settings.json"))
    enabled = settings.get("enabledPlugins", {})
    installed = known_plugin_names()
    groups = []
    for gname, members in modes.items():
        members = [m for m in members if m in installed]
        groups.append({
            "name": gname,
            "members": [{"name": m, "enabled": bool(enabled.get(m, False))} for m in members],
            # a group counts as "active" when every member is on and every plugin outside it is off
            "active": bool(members)
                and all(enabled.get(m, False) for m in members)
                and not any(enabled.get(p, False) for p in installed if p not in members),
        })
    unrgrouped = sorted(installed - {m for g in modes.values() for m in g})
    return {"title": "Groups", "groups": groups, "ungrouped": unrgrouped, "all_plugins": sorted(installed),
            "project_dir": project_dir, "known_projects": known_projects()}


def activate_group(name):
    modes = read_json(MODES_FILE, {})
    if name not in modes:
        return False, "unknown group"
    members = set(modes[name])
    errors = []
    for plugin in known_plugin_names():
        ok, err = toggle_plugin(plugin, plugin in members)
        if not ok:
            errors.append(f"{plugin}: {err}")
    return (not errors), "; ".join(errors)[:300]


def _frontmatter(path):
    """Pull name/description out of a SKILL.md-style YAML frontmatter without a YAML dep.
    Handles both inline ("description: foo") and folded block scalars
    ("description: >" followed by indented lines), which is how most SKILL.md
    files in the wild write a multi-line description.
    """
    name, desc = os.path.splitext(os.path.basename(path))[0], ""
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(4000)
        if head.startswith("---"):
            lines = head.split("---", 2)[1].splitlines()
            i = 0
            while i < len(lines):
                line = lines[i]
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip('"')
                elif line.startswith("description:"):
                    rest = line.split(":", 1)[1].strip()
                    if rest in (">", "|", ">-", "|-", ""):
                        parts = []
                        i += 1
                        while i < len(lines) and (lines[i][:1] in (" ", "\t")):
                            parts.append(lines[i].strip())
                            i += 1
                        desc = " ".join(parts)
                        continue
                    desc = rest.strip('"')
                i += 1
    except Exception:
        pass
    return name, desc


def _list_agents(dir_path):
    out = []
    if os.path.isdir(dir_path):
        for fn in sorted(os.listdir(dir_path)):
            if fn.endswith(".md"):
                path = os.path.join(dir_path, fn)
                name, desc = _frontmatter(path)
                out.append({"name": name, "desc": desc, "path": path})
    return out


def _walk_skills(root):
    """root 아래 SKILL.md를 가진 폴더를 {이름: 경로}로. 플러그인은 skills/misc/x처럼 중첩된다."""
    out = {}
    if not os.path.isdir(root):
        return out
    for base, dirs, files in os.walk(root):
        if "SKILL.md" in files:
            out[os.path.basename(base)] = base
            dirs[:] = []  # 스킬 폴더 안으로는 더 들어가지 않는다
    return out


def _list_skills(dir_path):
    """SKILL.md를 가진 폴더를 전부. mattpocock은 skills/misc/<이름>처럼 한 겹 더 들어가
    있어서, 바로 아래만 보면 스킬 37개가 0개로 보인다."""
    out = []
    for sid, path in sorted(_walk_skills(dir_path).items()):
        name, desc = _frontmatter(os.path.join(path, "SKILL.md"))
        out.append({"id": sid, "name": name, "desc": desc, "path": path})
    return out


READABLE_PATHS = set()  # populated by collect_instructions, checked by /api/content


# 프로젝트 루트 기준 (경로, 이 파일을 읽는 도구). '/'로 끝나면 디렉터리를 훑는다.
# AGENTS.md로 수렴하는 중이지만(30개 이상 도구가 읽는다) Claude Code는 CLAUDE.md만
# 읽고, 도구 고유 파일도 여전히 남아 있다 -- 그래서 드리프트가 생긴다.
# 경로 출처: github.com/intellectronica/ruler (도구별 출력 경로표), 각 도구 공식 문서.
INSTRUCTION_SOURCES = [
    ("CLAUDE.local.md", "Claude Code"),
    ("AGENTS.md", "Codex · Cursor · Zed +"),
    ("AGENT.md", "Amp (legacy)"),
    (".clinerules", "Cline"),
    (".cursorrules", "Cursor (legacy)"),
    (".cursor/rules/", "Cursor"),
    (".windsurfrules", "Windsurf"),
    (".roorules", "Roo Code"),
    (".roo/rules/", "Roo Code"),
    ("GEMINI.md", "Gemini CLI"),
    ("QWEN.md", "Qwen Code"),
    ("CONVENTIONS.md", "Aider"),
    ("CRUSH.md", "Crush"),
    ("WARP.md", "Warp"),
    (".goosehints", "Goose"),
    (".continuerules", "Continue"),
    (".continue/rules/", "Continue"),
    (".junie/guidelines.md", "Junie"),
    (".junie/rules/", "Junie"),
    (".aiassistant/rules/", "JetBrains AI"),
    (".kiro/steering/", "Kiro"),
    (".amazonq/rules/", "Amazon Q"),
    (".augment/rules/", "Augment"),
    (".augment-guidelines", "Augment (legacy)"),
    (".trae/rules/", "Trae"),
    (".openhands/microagents/", "OpenHands"),
    (".idx/airules.md", "Firebase Studio"),
    (".github/copilot-instructions.md", "Copilot"),
    (".github/instructions/", "Copilot"),
]

RULE_EXTS = (".md", ".mdc", ".txt", ".yaml", ".yml")


def _file_row(label, path, tool="Claude Code"):
    exists = os.path.isfile(path)
    st = os.stat(path) if exists else None
    if exists:
        READABLE_PATHS.add(path)
    return {
        "name": label,
        "exists": exists,
        "size": st.st_size if st else 0,
        "mtime": int(st.st_mtime) if st else 0,
        "path": path,
        "tool": tool,
    }


SKIP_DIRS = {"node_modules", "venv", ".venv", "dist", "build", "target", "vendor",
             "__pycache__", ".git", "Pods", ".next", ".nuxt", ".cache", "coverage"}

# 프로젝트 하나를 훑는 비용의 상한. 이 패널은 3초마다 다시 그려지므로 큰 저장소에서
# 디스크를 계속 긁고 있으면 안 된다. 넘으면 멈추고 잘렸다는 사실을 화면에 밝힌다.
SCAN_DIR_BUDGET = 4000
SCAN_ROW_CAP = 300
SCAN_TTL = 20.0
_scan_cache = {}  # project_dir -> (잰 시각, (행, 잘림))

# 지침은 루트에만 있지 않다. Claude Code는 하위 디렉터리의 CLAUDE.md를 읽고,
# 모노레포는 패키지마다 따로 둔다. 그래서 밑까지 내려간다.
_FLAT_NAMES = {"CLAUDE.md": "Claude Code"}
_NESTED_FLAT = []
for _rel, _tool in INSTRUCTION_SOURCES:
    if _rel.endswith("/"):
        continue
    (_NESTED_FLAT.append((_rel, _tool)) if "/" in _rel else _FLAT_NAMES.setdefault(_rel, _tool))
_DIR_SOURCES = [(r, t) for r, t in INSTRUCTION_SOURCES if r.endswith("/")]


def _scan_tree(project_dir):
    """project_dir 아래 전체에서 지침 파일을 찾는다. -> (행 목록, 잘렸는지)"""
    rows, dirs, truncated = [], 0, False
    for cur, subs, files in os.walk(project_dir):
        dirs += 1
        if dirs > SCAN_DIR_BUDGET or len(rows) > SCAN_ROW_CAP:
            truncated = True
            break
        subs[:] = sorted(d for d in subs if not d.startswith(".") and d not in SKIP_DIRS)
        rel_dir = os.path.relpath(cur, project_dir)
        prefix = "" if rel_dir == "." else rel_dir.replace(os.sep, "/") + "/"
        for fn in sorted(files):
            tool = _FLAT_NAMES.get(fn)
            if tool:
                rows.append(_file_row(prefix + fn, os.path.join(cur, fn), tool))
        for rel, tool in _NESTED_FLAT:          # .github/copilot-instructions.md 처럼 경로가 붙은 것
            path = os.path.join(cur, rel.replace("/", os.sep))
            if os.path.isfile(path):
                rows.append(_file_row(prefix + rel, path, tool))
        for rel, tool in _DIR_SOURCES:          # .cursor/rules/ 같은 디렉터리형 (점 폴더라 위 가지치기에 걸린다)
            d = os.path.join(cur, rel.replace("/", os.sep).rstrip(os.sep))
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if fn.endswith(RULE_EXTS):
                    rows.append(_file_row(prefix + rel + fn, os.path.join(d, fn), tool))
    return rows, truncated


def _instruction_rows(project_dir):
    """전체 트리를 훑되 결과는 잠깐 재사용한다 (폴링이 3초라 매번 훑을 이유가 없다)."""
    now = time.time()
    hit = _scan_cache.get(project_dir)
    if hit and now - hit[0] < SCAN_TTL:
        return hit[1]
    rows, truncated = _scan_tree(project_dir)
    rows = [r for r in rows if r["name"] != "CLAUDE.md"]  # 루트 것은 위쪽 고정 행이 보여준다
    _scan_cache[project_dir] = (now, (rows, truncated))
    return rows, truncated


# 스킬은 SKILL.md 형식이 공개 표준(agentskills.io)이라 폴더째 이식된다. 그런데 명세는
# **탐색 경로를 정하지 않아서**, 어디에 두느냐가 곧 어느 에이전트가 보느냐가 된다.
# Claude Code만 `.agents/skills`를 읽지 않는다는 게 이 표의 요점이다.
# 출처(2026-09 공식 문서): code.claude.com/docs/en/skills,
# learn.chatgpt.com/docs/build-skills, cursor.com/docs/context/skills,
# code.visualstudio.com/docs/copilot/customization/agent-skills, geminicli.com/docs/cli/skills
SKILL_AGENTS = ["Claude Code", "Codex", "Cursor", "Copilot", "Gemini CLI"]

SKILL_ROOTS_PROJECT = [
    (".claude/skills", ["Claude Code", "Cursor", "Copilot"]),
    (".agents/skills", ["Codex", "Cursor", "Copilot", "Gemini CLI"]),
    (".cursor/skills", ["Cursor"]),
    (".codex/skills", ["Cursor"]),
    (".github/skills", ["Copilot"]),
    (".gemini/skills", ["Gemini CLI"]),
]

SKILL_ROOTS_HOME = [
    (".claude/skills", ["Claude Code", "Cursor", "Copilot"]),
    (".agents/skills", ["Codex", "Cursor", "Copilot", "Gemini CLI"]),
    (".cursor/skills", ["Cursor"]),
    (".codex/skills", ["Cursor"]),
    (".copilot/skills", ["Copilot"]),
    (".gemini/skills", ["Gemini CLI"]),
]


def _scan_skill_root(root, label, agents, found):
    """같은 이름의 스킬은 한 행으로 합친다 -- 두 곳에 두면 보는 도구가 늘어난다."""
    if not os.path.isdir(root):
        return
    for name in sorted(os.listdir(root)):
        md = os.path.join(root, name, "SKILL.md")
        if not os.path.isfile(md):
            continue
        row = found.setdefault(name, {"name": name, "agents": [], "roots": [], "path": md})
        row["roots"].append(label)
        for a in agents:
            if a not in row["agents"]:
                row["agents"].append(a)
        READABLE_PATHS.add(md)


# 그룹의 스킬을 프로젝트에 심볼릭 링크해서 켜고 끈다. 도구별 설정 형식이 전부 다르지만
# (Claude Code만 프로젝트 단위 스위치가 있고 Gemini CLI는 형식이 또 다르다) **폴더를 훑는
# 것은 모두 똑같이 하므로**, 폴더에 있냐 없냐가 유일한 도구 공통 스위치다.
# 링크를 따라가는 것은 Claude Code·Gemini CLI·Codex·Copilot에서 실측 확인했다(ADR 10).
# 이 둘이면 그 네 도구가 전부 켜진다. Cursor는 .claude/.agents 둘 다 읽는다.
GROUP_LINK_DIRS = [".claude/skills", ".agents/skills"]


def plugin_skills():
    """설치된 플러그인 -> {스킬 이름: 폴더 경로}. 플러그인이 곧 스킬 묶음이다."""
    installed = read_json(os.path.join(CLAUDE_DIR, "plugins", "installed_plugins.json")).get("plugins", {})
    out = {}
    for name, entries in installed.items():
        skills = {}
        for e in entries:
            skills.update(_walk_skills(os.path.join(e.get("installPath", ""), "skills")))
        out[name] = skills
    return out


def _link_path(project_dir, rel, skill):
    return os.path.join(project_dir, rel.replace("/", os.sep), skill)


def skill_sources(project_dir):
    """{스킬 이름: 원본 폴더}. 원본은 플러그인 폴더나 사용자 스킬 폴더에서만 찾는다 --
    프로젝트 안의 링크를 원본으로 삼으면 자기 자신을 가리키게 된다."""
    out = {}
    for skills in plugin_skills().values():
        out.update(skills)
    for rel, _agents in SKILL_ROOTS_HOME:
        root = os.path.join(HOME, rel.replace("/", os.sep))
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.isfile(os.path.join(d, "SKILL.md")):
                out.setdefault(name, d)
    return out


def skill_is_shared(project_dir, name):
    """이 프로젝트의 모든 스킬 폴더에 링크가 걸려 있나."""
    return all(os.path.islink(_link_path(project_dir, d, name)) for d in GROUP_LINK_DIRS)


def link_skill(name, on, project_dir):
    """스킬 하나를 이 프로젝트의 모든 에이전트에게 열거나 닫는다.
    원본이 어디에 있든(플러그인·~/.claude·~/.agents) 비어 있는 폴더만 채운다 --
    그래서 방향(claude->agents, agents->claude)을 따질 필요가 없다."""
    if not project_dir or not os.path.isdir(project_dir):
        return False, "project not found"
    src = skill_sources(project_dir).get(name)
    if not src:
        return False, "unknown skill"
    try:
        for rel in GROUP_LINK_DIRS:
            dst = _link_path(project_dir, rel, name)
            if on:
                if os.path.islink(dst):
                    if os.path.realpath(dst) == os.path.realpath(src):
                        continue
                    os.unlink(dst)
                elif os.path.exists(dst):
                    continue  # 진짜 폴더는 사용자 것이다. 건드리지 않는다.
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.symlink(src, dst)
            elif os.path.islink(dst):
                os.unlink(dst)  # 링크만 지운다
    except Exception as e:
        return False, str(e)
    return True, ""


def _common_agents(skills):
    """섹션의 스킬이 모두 공유하는 에이전트. 줄마다 같은 뱃지를 되풀이하지 않기 위한 것."""
    sets = [set(sk["agents"]) for sk in skills]
    return [a for a in SKILL_AGENTS if all(a in x for x in sets)] if sets else []


def _skill_root_index(project_dir):
    """스킬 폴더들을 훑어 {이름: (볼 수 있는 에이전트, 어느 폴더)}."""
    found = {}
    for rel, agents in SKILL_ROOTS_PROJECT:
        _scan_skill_root(os.path.join(project_dir, rel.replace("/", os.sep)), rel, agents, found)
    for rel, agents in SKILL_ROOTS_HOME:
        _scan_skill_root(os.path.join(HOME, rel.replace("/", os.sep)), "~/" + rel, agents, found)
    return found


def collect_skills(ctx):
    """스킬 한 탭. 플러그인이 준 것과 단독으로 놓인 것을 한 화면에 둔다 --
    사용자에게 그 둘은 '스킬'이라는 한 가지이고, 출처만 다르다."""
    project_dir = default_project_dir(ctx)
    index = _skill_root_index(project_dir)
    sources = skill_sources(project_dir)
    settings = read_json(os.path.join(CLAUDE_DIR, "settings.json"))
    enabled = settings.get("enabledPlugins", {})
    installed = read_json(os.path.join(CLAUDE_DIR, "plugins", "installed_plugins.json")).get("plugins", {})
    marketplaces = read_json(os.path.join(CLAUDE_DIR, "plugins", "known_marketplaces.json"))
    modes = read_json(MODES_FILE)
    denied = set(read_json(os.path.join(project_dir, ".claude", "settings.json"))
                 .get("permissions", {}).get("deny", []))

    def decorate(skill, fallback_agents):
        hit = index.get(skill["id"])
        agents = hit["agents"] if hit else list(fallback_agents)
        skill["agents"] = agents
        skill["missing"] = [a for a in SKILL_AGENTS if a not in agents]
        skill["roots"] = hit["roots"] if hit else []
        skill["shared"] = skill_is_shared(project_dir, skill["id"])
        skill["linkable"] = skill["id"] in sources
        READABLE_PATHS.add(os.path.join(skill["path"], "SKILL.md"))
        return skill

    rows = []
    for name, entries in installed.items():
        entry = entries[0] if entries else {}
        install_path = entry.get("installPath", "")
        mp_name = name.split("@", 1)[1] if "@" in name else None
        mp_src = (marketplaces.get(mp_name) or {}).get("source", {})
        skills = _list_skills(os.path.join(install_path, "skills")) if install_path else []
        for sk in skills:
            # 플러그인 폴더 자체는 Claude Code만 읽는다. 그룹을 프로젝트에 링크했다면
            # 같은 이름이 스킬 폴더에도 있어 index 쪽 값이 이긴다.
            decorate(sk, ["Claude Code"])
            sk["blocked"] = f"Skill({name}:{sk['id']})" in denied
        rows.append({
            "name": name,
            "section_agents": _common_agents(skills),
            "version": entry.get("version", "?"),
            "enabled": bool(enabled.get(name, False)),
            "claude_only": True,
            "modes": [m for m, plist in modes.items() if name in plist],
            "source": mp_src.get("repo") or mp_src.get("path") or mp_name or "?",
            "skills": skills,
        })

    # 플러그인에 속하지 않은 스킬들. 스위치가 없다 -- 폴더에 있으면 켜진 것이다.
    plugin_ids = {sk["id"] for r in rows for sk in r["skills"]}
    loose = []
    for sid, hit in sorted(index.items()):
        if sid in plugin_ids:
            continue
        name, desc = _frontmatter(os.path.join(hit["path"]))
        loose.append(decorate({"id": sid, "name": name, "desc": desc,
                               "path": os.path.dirname(hit["path"])}, []))
    if loose:
        rows.append({
            "name": "", "version": "", "enabled": None, "claude_only": False,
            "section_agents": _common_agents(loose),
            "modes": [], "source": ", ".join(sorted({r for sk in loose for r in sk["roots"]})),
            "skills": loose,
        })

    return {
        "title": "Skills (who can see them)",
        "rows": rows,
        "agents": SKILL_AGENTS,
        "project_dir": project_dir,
        "known_projects": known_projects(),
    }


def collect_instructions(ctx):
    project_dir = default_project_dir(ctx)
    rows = [
        _file_row("Global CLAUDE.md", os.path.join(CLAUDE_DIR, "CLAUDE.md")),
        _file_row("Project CLAUDE.md", os.path.join(project_dir, "CLAUDE.md")),
    ]
    sub_rows, truncated = _instruction_rows(project_dir)
    rows += sub_rows
    agents = _list_agents(os.path.join(CLAUDE_DIR, "agents")) + _list_agents(os.path.join(project_dir, ".claude", "agents"))
    for a in agents:
        READABLE_PATHS.add(a["path"])
    return {
        "title": "Instructions & agents (read-only)",
        "files": rows,
        "truncated": truncated,
        "agents": agents,
        "project_dir": project_dir,
        "known_projects": known_projects(),
    }


def read_content(path):
    if path not in READABLE_PATHS:
        return None, "path not allowed"
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read(50_000)
        return text, ""
    except Exception as e:
        return None, str(e)


PANELS = [collect_groups, collect_skills, collect_instructions, collect_update]


def known_plugin_names():
    installed = read_json(os.path.join(CLAUDE_DIR, "plugins", "installed_plugins.json")).get("plugins", {})
    return set(installed.keys())


def toggle_plugin(name, enable):
    if name not in known_plugin_names():
        return False, "unknown plugin"
    verb = "enable" if enable else "disable"
    try:
        r = subprocess.run([CLAUDE_BIN, "plugin", verb, name], capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return False, (r.stderr or r.stdout).strip()[:200]
        return True, ""
    except Exception as e:
        return False, str(e)


def modify_group(action, group, plugin):
    group = (group or "").strip()
    if not group:
        return False, "group name required"
    if plugin not in known_plugin_names():
        return False, "unknown plugin"
    modes = read_json(MODES_FILE, {})
    if action == "add":
        modes.setdefault(group, [])
        if plugin not in modes[group]:
            modes[group].append(plugin)
    elif action == "remove":
        if group in modes and plugin in modes[group]:
            modes[group].remove(plugin)
            if not modes[group]:
                del modes[group]
    else:
        return False, "unknown action"
    try:
        with open(MODES_FILE, "w") as f:
            json.dump(modes, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return False, str(e)
    return True, ""


def modify_skill_permission(action, plugin, skill, project_dir):
    project_dir = project_dir or PROJECT_DIR
    if plugin not in known_plugin_names():
        return False, "unknown plugin"
    if not skill:
        return False, "skill id required"
    settings_path = os.path.join(project_dir, ".claude", "settings.json")
    settings = read_json(settings_path, {})
    perms = settings.setdefault("permissions", {})
    deny = perms.setdefault("deny", [])
    entry = f"Skill({plugin}:{skill})"
    if action == "block":
        if entry not in deny:
            deny.append(entry)
    elif action == "unblock":
        if entry in deny:
            deny.remove(entry)
    else:
        return False, "unknown action"
    if not deny:
        perms.pop("deny", None)
    if not perms:
        settings.pop("permissions", None)
    try:
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        with open(settings_path, "w") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return False, str(e)
    return True, ""


_last_cpu = [time.monotonic(), sum(os.times()[:2])]


def proc_usage():
    """이 서버 자신의 메모리와 CPU. 폴링하는 도구라 스스로 얼마나 먹는지 보여야 한다.
    stdlib만 쓴다 -- 이걸 위해 psutil을 넣을 이유는 없다."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        rss *= 1024  # 리눅스는 KB, macOS는 바이트로 준다
    now, cpu = time.monotonic(), sum(os.times()[:2])
    dw, dc = now - _last_cpu[0], cpu - _last_cpu[1]
    _last_cpu[0], _last_cpu[1] = now, cpu
    return {"mb": round(rss / 1048576, 1), "cpu": round(dc / dw * 100, 1) if dw > 0.05 else None}


def build_state(project_dir=None):
    ctx = {"project_dir": project_dir}
    return {"ts": time.time(), "proc": proc_usage(), "panels": [p(ctx) for p in PANELS]}


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>Agent HUD</title>
<style>
:root{
  --bg:#f5f6f8;--panel:#ffffff;--border:#e5e7eb;--text:#1d2129;--dim:#8a919e;
  --accent:#3182f6;--on:#00a870;--off:#5f6673;--on-tint:#e3f9ef;--off-tint:#eef0f2;
  --shadow:0 1px 2px rgba(0,0,0,.04),0 1px 6px rgba(0,0,0,.03);
}
:root[data-theme="dark"]{
  --bg:#0d1117;--panel:#161b22;--border:#262c36;--text:#e6edf3;--dim:#8b949e;
  --accent:#58a6ff;--on:#56d364;--off:#8b949e;--on-tint:rgba(63,185,80,.14);--off-tint:rgba(139,148,158,.12);
  --shadow:0 1px 2px rgba(0,0,0,.3),0 1px 6px rgba(0,0,0,.25);
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,"SF Pro Text","Pretendard",Inter,sans-serif;margin:0 auto;padding:28px;max-width:976px;-webkit-font-smoothing:antialiased}
h1{margin:0;display:flex;align-items:baseline;gap:.13em;font-size:23px;letter-spacing:-.02em;line-height:1.1}
h1 .wm-a{font-weight:400;color:var(--text)}
h1 .wm-b{font-weight:800;color:var(--text)}
#h1sub{display:block;margin-top:4px;font-size:10px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--dim);opacity:.7;font-family:ui-monospace,"SF Mono",Menlo,monospace}
.rule-note{border-left:2px solid var(--border);padding:2px 0 2px 10px;margin-bottom:14px;
  color:var(--dim);font-size:12px;line-height:1.6;max-width:74ch}
.rule-note b{color:var(--text);font-weight:600}
#h1sub:lang(ko){letter-spacing:0;text-transform:none;font-family:inherit;font-size:11.5px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));grid-auto-flow:dense;gap:12px}
.card{background:var(--panel);border:1px solid var(--border);box-shadow:var(--shadow);border-radius:8px;padding:14px}
.card.wide{grid-column:1/-1}
.empty{color:var(--dim);font-size:13px;padding:6px 0;display:flex;align-items:center;gap:8px}
.card h2{font-size:12px;color:var(--dim);margin:0 0 10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
.row{display:flex;align-items:center;justify-content:space-between;gap:6px 12px;flex-wrap:wrap;padding:8px 0;border-bottom:1px solid var(--border);font-size:14px;font-weight:600}
.row:last-child{border-bottom:none}
.row.sub{padding-left:18px;font-size:13px;font-weight:500}
.section{margin-bottom:6px}
.sec-head{border-bottom:0;padding:10px 0 4px;gap:10px;align-items:flex-start}
.sec-left{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0;flex:1}
.sec-name{overflow-wrap:anywhere;min-width:0}
.sec-right{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end;flex:0 0 auto}
.sec-meta{display:flex;align-items:center;justify-content:space-between;gap:10px 14px;
  flex-wrap:wrap;padding:0 0 10px;border-bottom:1px solid var(--border)}
.badges{display:flex;align-items:center;gap:5px 7px;flex-wrap:wrap;min-width:0}
.skill-row{align-items:center;justify-content:flex-start;gap:10px;flex-wrap:wrap}
.skill-text{display:flex;flex-direction:column;gap:2px;min-width:0;flex:1 1 240px}
.skill-name{font-weight:600;color:var(--text)}
.skill-desc{font-size:12px;line-height:1.5}
.note.sub{padding-left:18px}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:8px;cursor:pointer;transition:transform .1s}
.dot:hover{transform:scale(1.4)}
.dot.busy{opacity:.4;cursor:wait}
.on{background:var(--on)} .off{background:var(--off)}
.switch{display:inline-flex;align-items:center;justify-content:center;min-width:44px;text-align:center;font-size:11px;font-weight:700;letter-spacing:.02em;padding:3px 8px;border-radius:4px;cursor:pointer;flex:0 0 auto;user-select:none;transition:background .12s,color .12s,transform .12s}
.sw-on.switch:hover{background:var(--on);color:var(--panel);border-color:var(--on)}
.sw-off.switch:hover{background:var(--accent);color:#fff;border-color:var(--accent)}
.switch:active{transform:scale(.96)}
.switch.busy{opacity:.4;cursor:wait}
.lang-opt{padding:6px 12px;cursor:pointer;color:var(--dim);transition:background .12s,color .12s;font-size:12px}
.lang-opt:hover{color:var(--text)}
.lang-opt.active{background:var(--accent);color:#fff}
.quiet-toggle .lang-opt.active{background:var(--off-tint);color:var(--text)}
.tab-opt{padding:7px 14px;cursor:pointer;color:var(--dim);font-size:13px;font-weight:600;transition:background .12s,color .12s}
.tab-opt:not(:last-child){border-right:1px solid var(--border)}
.tab-opt:hover{color:var(--text)}
.tab-opt.active{background:var(--accent);color:#fff}
.sw-on{background:var(--on-tint);color:var(--on);border:1px solid color-mix(in srgb,var(--on) 35%,transparent)}
.sw-off{background:var(--off-tint);color:var(--off);border:1px solid var(--border)}
.note{color:var(--dim);font-size:12px;margin-top:6px;line-height:1.65;max-width:74ch;text-wrap:pretty}
/* 74ch는 여러 줄 산문에는 맞지만, 한 줄이면 될 안내를 굳이 접는다 */
.note.wide{max-width:none}
.clickable{cursor:pointer}
.row.clickable:hover{background:var(--off-tint)}
span.clickable:hover,div.skill-desc.clickable:hover{color:var(--accent)}
.content{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px;margin:6px 0 10px;font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:12px;max-height:360px;overflow:auto;display:none}
.content.open{display:block}
.badge{background:var(--accent);color:#fff;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700}
.dim{color:var(--dim);font-size:13px}
.skill-desc{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.share{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--dim);margin-left:auto;
  white-space:nowrap;cursor:pointer;user-select:none;flex:0 0 auto}
.share:hover{color:var(--text)}
.share-done{color:var(--on)}
.share input{accent-color:var(--accent);cursor:pointer;margin:0}
.share.busy{opacity:.4;cursor:wait}
.agenttag{border:1px solid var(--border);padding:1px 7px;border-radius:999px;font-size:11px;white-space:nowrap}
.agenttag.yes{color:var(--text)}
.agenttag.no{color:var(--dim);opacity:.45;text-decoration:line-through}
.tooltag{border:1px solid var(--border);color:var(--dim);padding:1px 7px;border-radius:999px;font-size:11px;white-space:nowrap;margin-left:8px}
.tag{font-size:11px;color:var(--dim);font-family:ui-monospace,"SF Mono",Menlo,monospace;white-space:nowrap}
.tag.danger{cursor:pointer}
.tag.danger:hover{color:#f04452}
.mono{font-family:ui-monospace,"SF Mono",Menlo,monospace}
.card-action{font-size:12px;font-weight:700;color:var(--accent);cursor:pointer;white-space:nowrap}
.card-action:hover{opacity:.75}
.btn{border:1px solid var(--accent);color:var(--accent);background:transparent;border-radius:4px;
  padding:4px 10px;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap}
.btn:hover{background:var(--accent);color:var(--panel)}
.btn-on{border-color:var(--on);color:var(--on);background:var(--on-tint)}
.btn-on:hover{background:var(--on);color:var(--panel)}
#ts{color:var(--dim);font-size:11px;margin-top:16px;display:flex;align-items:center;gap:8px}
#period{background:transparent;color:var(--dim);border:1px solid var(--border);border-radius:4px;
  padding:1px 4px;font-size:11px;font-family:inherit;cursor:pointer}
#period:hover{color:var(--text)}
</style></head><body>
<div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:20px">
  <span>
    <h1><span class="wm-a">Agent</span><span class="wm-b">HUD</span></h1>
    <span id="h1sub"></span>
  </span>
  <span style="display:flex;gap:8px">
    <span id="langToggle" style="display:inline-flex;border:1px solid var(--border);border-radius:10px;overflow:hidden;font-size:11px;font-weight:700;letter-spacing:.03em">
      <span id="langEn" class="lang-opt">EN</span><span id="langKo" class="lang-opt">한국어</span>
    </span>
    <span id="themeToggle" class="quiet-toggle" style="display:inline-flex;border:1px solid var(--border);border-radius:10px;overflow:hidden;font-size:11px;font-weight:700;letter-spacing:.03em">
      <span id="themeLight" class="lang-opt">☀</span><span id="themeDark" class="lang-opt">☾</span>
    </span>
  </span>
</div>
<div class="note" id="updateBanner" style="margin-bottom:12px;display:none"></div>
<div id="tabs" style="display:inline-flex;border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:12px"></div>
<div id="applyBanner" class="rule-note"></div>
<div class="grid" id="app"></div>
<div style="max-width:920px;margin-top:16px"><a id="fbLink" class="card-action" href="#" target="_blank" rel="noopener"></a></div>
<div id="ts"><span id="tsText"></span><select id="period" title=""></select></div>
<script>
const T = {
  en: {
    banner: 'Plugin changes take effect <b>next session</b>. Everything else is immediate.',
    tagline: 'local dashboard',
    title_groups: 'Groups', title_instructions: 'Instructions & agents', title_skills: 'Skills',
  skills_note: 'Struck through = that agent cannot see the skill. Only Claude Code looks inside plugin folders. Tick the box and every agent finds it.',
  no_skills: 'No skills found in any known folder.',
  link_failed: 'Could not share that skill: ',
  loose_skills: 'Skills not from a plugin',
    on: 'ON', off: 'OFF',
    active_tip: 'On, and every plugin outside this group is off',
    activate_tip: 'Turn this group on and every other plugin off (next session)',
    plugins_count: n => n + (n === 1 ? ' plugin' : ' plugins'),
    remove: 'remove ✕', remove_tip: (m,g) => `take ${m} out of "${g}"`,
    remove_confirm: (m,g) => `Remove ${m} from group "${g}"?`,
    add_plugin_ph: '+ add a plugin to this group…',
    new_group: '+ create a new group', new_group_tip: 'Plugins you switch on together. For example one set for coding, one for video work',
    new_group_name_prompt: 'Name for the new group (e.g. "dev", "video"):',
    new_group_first_prompt: 'Which plugin should it start with?\n',
    not_in_group: list => 'Not in any group yet: ' + list,
    groups_legend: 'A group is a set of plugins you use together. Turning one on turns the others off, everywhere on this computer.',
    switch_confirm: (g,list) => `Turn on only "${g}"?\n\nOn: ${list}\nOff: every other plugin`,
    no_project: 'No projects yet. Run Claude Code inside a project folder and it will show up here',
    project_label: 'project: ',
  not_found: 'not found',
  agents_claude_only: 'Subagents below are Claude Code only.',
  share_to: names => 'also use in ' + names.join(', '),
  share_done: 'in every agent',
  share_all_tip: 'Makes this skill usable by those agents in this project. Links it into the folders it is missing from; the original never moves.',
  scan_truncated: 'This project is large, so the scan stopped early. Some instruction files further down may be missing.',
    no_subagents: 'No subagents registered',
    loading: 'loading…', error: 'error: ',
    toggle_failed: 'Could not switch that plugin: ', group_update_failed: 'Could not change the group: ',
    activation_failed: 'Could not turn that group on: ', skill_update_failed: 'Could not change that skill: ',
    plugin_on_tip: 'On. Click to turn it off (next session)',
    plugin_off_tip: 'Off. Click to turn it on (next session)',
    skills_count: n => n + (n === 1 ? ' skill' : ' skills'),
    group_tag: g => 'group: ' + g, group_tag_tip: 'Manage groups in the Groups tab',
    from: 'from: ',
    blocked: 'BLOCKED', allowed: 'ALLOWED',
    blocked_tip: 'Blocked in this project. Click to allow it again',
    allowed_tip: 'Click to block this one skill in this project',
    read_full_tip: 'Read the full description',
    no_skills_found: 'No skills',
    updated: 'updated ', every_n: n => `every ${n}s`, paused: 'paused',
    usage: (mb, cpu) => `${mb}MB` + (cpu === null ? '' : ` · ${cpu}% CPU`),
    period_tip: 'How often this page re-reads the files',
    switching: 'switching…',
    update_available: (v, latest, repo) => `↑ v${latest} available (you're on v${v}) — <a href="https://github.com/${repo}/releases/latest" target="_blank" rel="noopener">see release</a>, then <code>git pull</code> in this folder`,
    feedback_open: 'send feedback ↗',
  },
  ko: {
    banner: '플러그인은 <b>다음 세션부터</b>, 나머지는 바로 반영됩니다.',
    tagline: '로컬 대시보드',
    title_groups: '그룹', title_instructions: '지침 · 에이전트', title_skills: '스킬',
  skills_note: '취소선 = 그 에이전트가 못 보는 스킬. 플러그인 폴더는 Claude Code만 보기 때문입니다. 체크박스를 켜면 모든 에이전트가 찾습니다.',
  no_skills: '어느 폴더에서도 스킬을 못 찾았습니다.',
  link_failed: '스킬을 넣지 못했습니다: ',
  loose_skills: '플러그인 밖의 스킬',
    on: '켜짐', off: '꺼짐',
    active_tip: '지금 이 그룹만 켜져 있습니다',
    activate_tip: '이 그룹만 켜고 나머지는 끕니다. 다음 세션부터 반영됩니다',
    plugins_count: n => '플러그인 ' + n + '개',
    remove: '빼기 ✕', remove_tip: (m,g) => `"${g}" 그룹에서 ${m} 빼기`,
    remove_confirm: (m,g) => `"${g}" 그룹에서 ${m} 뺄까요?`,
    add_plugin_ph: '+ 이 그룹에 플러그인 추가…',
    new_group: '+ 새 그룹 만들기', new_group_tip: '함께 켜고 끌 플러그인을 묶어둡니다. 예를 들어 개발용, 영상제작용',
    new_group_name_prompt: '새 그룹 이름 (예: "개발", "영상제작"):',
    new_group_first_prompt: '어떤 플러그인부터 넣을까요?\n',
    not_in_group: list => '아직 어느 그룹에도 안 넣은 플러그인: ' + list,
    groups_legend: '함께 쓰는 플러그인을 묶어둔 것입니다. 하나를 켜면 나머지 그룹은 같이 꺼지고, 이 컴퓨터 전체에 적용됩니다.',
    switch_confirm: (g,list) => `"${g}" 그룹만 켤까요?\n\n켜짐: ${list}\n꺼짐: 나머지 플러그인 전부`,
    no_project: '아직 열어본 프로젝트가 없습니다. 프로젝트 폴더에서 Claude Code를 실행하면 여기 나타납니다',
    project_label: '프로젝트: ',
  not_found: '없음',
  agents_claude_only: '서브에이전트는 Claude Code만 읽습니다.',
  share_to: names => names.join('·') + '도 쓰기',
  share_done: '전부 쓰는 중',
  share_all_tip: '이 프로젝트에서 그 에이전트들도 이 스킬을 쓰게 합니다. 빠져 있는 폴더에만 링크를 채우고, 원본은 움직이지 않습니다.',
  scan_truncated: '프로젝트가 커서 탐색을 중간에 멈췄습니다. 더 아래에 있는 지침 파일은 빠졌을 수 있습니다.',
    no_subagents: '등록된 서브에이전트 없음',
    loading: '불러오는 중…', error: '오류: ',
    toggle_failed: '켜고 끄지 못했습니다: ', group_update_failed: '그룹을 바꾸지 못했습니다: ',
    activation_failed: '그룹을 켜지 못했습니다: ', skill_update_failed: '스킬을 바꾸지 못했습니다: ',
    plugin_on_tip: '켜져 있습니다. 누르면 꺼집니다 (다음 세션부터)',
    plugin_off_tip: '꺼져 있습니다. 누르면 켜집니다 (다음 세션부터)',
    skills_count: n => '스킬 ' + n + '개',
    group_tag: g => '그룹: ' + g, group_tag_tip: '그룹 탭에서 관리합니다',
    from: '출처: ',
    blocked: '차단', allowed: '허용',
    blocked_tip: '이 프로젝트에서 막아둔 스킬입니다. 누르면 풉니다',
    allowed_tip: '누르면 이 프로젝트에서만 막습니다',
    read_full_tip: '설명 전체 보기',
    no_skills_found: '스킬이 없습니다',
    updated: '갱신 ', every_n: n => `${n}초마다`, paused: '멈춤',
    usage: (mb, cpu) => `${mb}MB` + (cpu === null ? '' : ` · CPU ${cpu}%`),
    period_tip: '이 화면이 파일을 얼마나 자주 다시 읽을지',
    switching: '바꾸는 중…',
    update_available: (v, latest, repo) => `↑ v${latest} 나왔습니다 (지금은 v${v}) — <a href="https://github.com/${repo}/releases/latest" target="_blank" rel="noopener">릴리스 보기</a> 후 이 폴더에서 <code>git pull</code>`,
    feedback_open: '피드백 보내기 ↗',
  },
};
let lang = new URLSearchParams(location.search).get('lang') || localStorage.getItem('agent-hud-lang') || 'en';
function t(){ return T[lang]; }
function renderLangToggle(){
  document.documentElement.lang = lang;
  document.getElementById('langEn').classList.toggle('active', lang === 'en');
  document.getElementById('langKo').classList.toggle('active', lang === 'ko');
}
function setLang(l){
  lang = l;
  localStorage.setItem('agent-hud-lang', lang);
  renderLangToggle();
  document.getElementById('applyBanner').innerHTML = t().banner;
  document.getElementById('h1sub').textContent = t().tagline;
  renderPeriod();
  renderTabs();
  tick();
}
document.getElementById('langEn').onclick = () => setLang('en');
document.getElementById('langKo').onclick = () => setLang('ko');
renderLangToggle();
document.getElementById('applyBanner').innerHTML = t().banner;
document.getElementById('h1sub').textContent = t().tagline;

let theme = localStorage.getItem('agent-hud-theme') || 'dark';
function renderTheme(){
  document.documentElement.setAttribute('data-theme', theme);
  document.getElementById('themeLight').classList.toggle('active', theme === 'light');
  document.getElementById('themeDark').classList.toggle('active', theme === 'dark');
}
function setTheme(th){
  theme = th;
  localStorage.setItem('agent-hud-theme', theme);
  renderTheme();
}
document.getElementById('themeLight').onclick = () => setTheme('light');
document.getElementById('themeDark').onclick = () => setTheme('dark');
renderTheme();
const shortAgent = a => a.replace(' CLI','');
const fmtTime = ts => new Date(ts*1000).toLocaleDateString(undefined,{month:'2-digit',day:'2-digit'}) + ' ' + new Date(ts*1000).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'});
const TITLE_MAP = { Groups: 'title_groups', 'Instructions & agents (read-only)': 'title_instructions', 'Skills (who can see them)': 'title_skills' };
const TABS = ['Groups', 'Skills (who can see them)', 'Instructions & agents (read-only)'];
// ?tab= 이 있으면 그걸 쓴다. 특정 탭을 링크로 걸거나 캡처할 때 필요하다.
let activeTab = new URLSearchParams(location.search).get('tab') || localStorage.getItem('agent-hud-tab') || 'Groups';
// 탭 이름이 바뀌면 저장된 값이 어느 패널과도 안 맞아 빈 화면이 된다.
if(!TABS.includes(activeTab)) activeTab = TABS[0];
function renderTabs(){
  const bar = document.getElementById('tabs');
  bar.innerHTML = '';
  for(const tabKey of TABS){
    const el = document.createElement('span');
    el.className = 'tab-opt' + (activeTab === tabKey ? ' active' : '');
    el.textContent = t()[TITLE_MAP[tabKey]];
    el.onclick = () => { activeTab = tabKey; localStorage.setItem('agent-hud-tab', tabKey); renderTabs(); rerender(); };
    bar.appendChild(el);
  }
}
renderTabs();
let polling = true;
// tick()은 polling=false면 즉시 반환한다(파일 내용을 펼쳐두면 그렇게 된다).
// 사용자가 직접 일으킨 재렌더는 그 가드를 넘어가야 한다 -- 재렌더가 열린 박스를
// 어차피 지우므로 여기서 polling도 같이 되살린다.
function rerender(){ polling = true; return tick(); }
let selectedProject = localStorage.getItem('agent-hud-project') || '';
let currentProjectDir = '';
const contentCache = {};
// ?open=<플러그인> 으로 펼친 채 열 수 있다 (?tab= 과 같은 이유)
const skillsOpen = Object.fromEntries((new URLSearchParams(location.search).get('open')||'')
  .split(',').filter(Boolean).map(k => [k, true]));
function stateUrl(){
  return '/api/state' + (selectedProject ? ('?project=' + encodeURIComponent(selectedProject)) : '');
}
function projectLabel(dir){
  return (dir && dir !== '/') ? dir : t().no_project;
}
async function showContent(path, box, caretEl){
  const open = box.classList.contains('open');
  if(open){ box.classList.remove('open'); polling = true; if(caretEl) caretEl.textContent = '▸ '; return; }
  polling = false;
  if(caretEl) caretEl.textContent = '▾ ';
  if(!contentCache[path]){
    box.classList.add('open'); box.textContent = t().loading;
    const r = await fetch('/api/content?path=' + encodeURIComponent(path));
    const d = await r.json();
    contentCache[path] = d.ok ? d.text : (t().error + d.error);
  }
  box.textContent = contentCache[path];
  box.classList.add('open');
}
async function toggle(name, enable, dotEl){
  polling = false; dotEl.classList.add('busy');
  try{
    const r = await fetch('/api/toggle', {method:'POST', body: JSON.stringify({name, enable})});
    const d = await r.json();
    if(!d.ok) alert(t().toggle_failed + (d.error || t().error));
  } catch(e){ alert(t().toggle_failed + e); }
  polling = true;
  await tick();
}
async function editGroup(action, group, plugin){
  polling = false;
  try{
    const r = await fetch('/api/group', {method:'POST', body: JSON.stringify({action, group, plugin})});
    const d = await r.json();
    if(!d.ok) alert(t().group_update_failed + (d.error || t().error));
  } catch(e){ alert(t().group_update_failed + e); }
  polling = true;
  await tick();
}
async function linkSkill(names, on, el){
  polling = false; el.classList.add('busy');
  try{
    const r = await fetch('/api/linkskill', {method:'POST', body: JSON.stringify({names: [].concat(names), on, project: currentProjectDir})});
    const d = await r.json();
    if(!d.ok) alert(t().link_failed + (d.error || t().error));
  } catch(e){ alert(t().link_failed + e); }
  polling = true;
  await tick();
}
async function activateGroup(name, btn){
  polling = false; btn.classList.add('busy'); btn.textContent = t().switching;
  try{
    const r = await fetch('/api/activate', {method:'POST', body: JSON.stringify({group: name})});
    const d = await r.json();
    if(!d.ok) alert(t().activation_failed + (d.error || t().error));
  } catch(e){ alert(t().activation_failed + e); }
  polling = true;
  await tick();
}
async function toggleSkill(plugin, skill, block, dotEl){
  polling = false; dotEl.classList.add('busy');
  try{
    const r = await fetch('/api/skill', {method:'POST', body: JSON.stringify({
      action: block ? 'block' : 'unblock', plugin, skill, project: currentProjectDir
    })});
    const d = await r.json();
    if(!d.ok) alert(t().skill_update_failed + (d.error || t().error));
  } catch(e){ alert(t().skill_update_failed + e); }
  polling = true;
  await tick();
}
// 피드백은 GitHub Issues로 받는다. 이 도구를 설치할 수 있는 사람은 전부 GitHub 계정이
// 있으므로(설치가 git clone + 셸 스크립트 + settings.json 편집이다), 별도 수신 서버를
// 두는 것보다 이슈 폼 하나가 낫다. 버전은 링크가 미리 채워 보낸다.
function renderFeedback(upd){
  const a = document.getElementById('fbLink');
  a.textContent = t().feedback_open;
  a.href = `https://github.com/${upd.repo}/issues/new?template=feedback.yml&version=${encodeURIComponent(upd.version)}`;
}
async function tick(){
  if(!polling) return;
  const r = await fetch(stateUrl()); const d = await r.json();
  const upd = d.panels.find(p => p.panel === 'update');
  const updEl = document.getElementById('updateBanner');
  if(upd && upd.has_update){
    updEl.innerHTML = t().update_available(upd.version, upd.latest, upd.repo);
    updEl.style.display = '';
  } else {
    updEl.style.display = 'none';
  }
  if(upd) renderFeedback(upd);
  const app = document.getElementById('app'); app.innerHTML='';
  for(const p of d.panels){
    if(p.project_dir) currentProjectDir = p.project_dir;
    if(p.title !== activeTab) continue;
    const c = document.createElement('div'); c.className='card wide';
    const h = document.createElement('h2'); h.textContent = TITLE_MAP[p.title] ? t()[TITLE_MAP[p.title]] : p.title;
    if(p.title === 'Groups'){
      const headerRow = document.createElement('div'); headerRow.style.cssText='display:flex;align-items:center;justify-content:space-between;margin-bottom:6px';
      h.style.margin='0';
      const newBtn = document.createElement('span'); newBtn.className='card-action';
      newBtn.textContent = t().new_group;
      newBtn.title = t().new_group_tip;
      newBtn.onclick = () => {
        const name = prompt(t().new_group_name_prompt);
        if(!name) return;
        const first = prompt(t().new_group_first_prompt + p.all_plugins.join('\n'));
        if(first) editGroup('add', name.trim(), first.trim());
      };
      headerRow.appendChild(h); headerRow.appendChild(newBtn);
      c.appendChild(headerRow);
      const legend = document.createElement('div'); legend.className='note'; legend.style.marginBottom='14px';
      legend.textContent = t().groups_legend;
      c.appendChild(legend);
      for(const g of p.groups){
        const wrap = document.createElement('div');
        const el = document.createElement('div'); el.className='row';

        const left = document.createElement('span');
        const act = document.createElement('span');
        act.className = 'switch ' + (g.active ? 'sw-on' : 'sw-off');
        act.textContent = g.active ? t().on : t().off;
        act.title = g.active ? t().active_tip : t().activate_tip;
        if(!g.active){
          act.onclick = () => { if(confirm(t().switch_confirm(g.name, g.members.map(m=>m.name).join(', ') || '(none)'))) activateGroup(g.name, act); };
        }
        left.className = 'sec-left';
        left.appendChild(act);
        const gname = document.createElement('span'); gname.textContent = g.name;
        left.appendChild(gname);
        const cnt = document.createElement('span'); cnt.className='tag';
        cnt.textContent = t().plugins_count(g.members.length);
        left.appendChild(cnt);
        el.appendChild(left);

        wrap.appendChild(el);

        for(const m of g.members){
          const mrow = document.createElement('div'); mrow.className='row sub';
          const mleft = document.createElement('span');
          const mdot = document.createElement('span'); mdot.className = 'dot ' + (m.enabled?'on':'off');
          mdot.style.cursor = 'default';
          mleft.appendChild(mdot);
          mleft.appendChild(document.createTextNode(m.name));
          const rm = document.createElement('span'); rm.className='tag clickable danger'; rm.textContent=t().remove;
          rm.title = t().remove_tip(m.name, g.name);
          rm.onclick = () => { if(confirm(t().remove_confirm(m.name, g.name))) editGroup('remove', g.name, m.name); };
          mrow.appendChild(mleft); mrow.appendChild(rm);
          wrap.appendChild(mrow);
        }

        const addRow = document.createElement('div'); addRow.className='row sub';
        const addSel = document.createElement('select');
        addSel.style.cssText='background:var(--bg);color:var(--dim);border:1px solid var(--border);border-radius:8px;padding:4px 8px;font-size:12px';
        const ph = document.createElement('option'); ph.value=''; ph.textContent=t().add_plugin_ph;
        addSel.appendChild(ph);
        for(const pl of p.all_plugins){
          if(g.members.some(m => m.name === pl)) continue;
          const o = document.createElement('option'); o.value=pl; o.textContent=pl;
          addSel.appendChild(o);
        }
        addSel.onchange = () => { if(addSel.value) editGroup('add', g.name, addSel.value); };
        addRow.appendChild(addSel);
        wrap.appendChild(addRow);
        c.appendChild(wrap);
      }

      if((p.ungrouped||[]).length){
        const note = document.createElement('div'); note.className='note';
        note.textContent = t().not_in_group(p.ungrouped.join(', '));
        c.appendChild(note);
      }
    } else if(p.files){
      c.appendChild(h);
      if(p.known_projects && p.known_projects.length > 1){
        const sel = document.createElement('select');
        sel.style.cssText = 'background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:6px 8px;margin-bottom:10px;font-size:12px;width:100%';
        for(const pr of p.known_projects){
          const opt = document.createElement('option'); opt.value = pr; opt.textContent = pr;
          if(pr === p.project_dir) opt.selected = true;
          sel.appendChild(opt);
        }
        sel.onchange = () => { selectedProject = sel.value; localStorage.setItem('agent-hud-project', sel.value); rerender(); };
        c.appendChild(sel);
      } else {
        const note = document.createElement('div'); note.className = 'note';
        note.textContent = t().project_label + projectLabel(p.project_dir);
        c.appendChild(note);
      }
      for(const f of p.files){
        const el = document.createElement('div'); el.className = 'row' + (f.exists ? ' clickable' : '');
        const left = document.createElement('span');
        const caret = document.createElement('span');
        caret.textContent = f.exists ? '▸ ' : '';
        left.appendChild(caret);
        left.insertAdjacentHTML('beforeend', `<span class="dot ${f.exists?'on':'off'}" style="cursor:default"></span>${f.name}<span class="tooltag">${f.tool}</span>`);
        const sizeSpan = document.createElement('span'); sizeSpan.className = 'dim';
        sizeSpan.textContent = f.exists ? f.size + 'B · ' + fmtTime(f.mtime) : t().not_found;
        el.appendChild(left); el.appendChild(sizeSpan);
        c.appendChild(el);
        const box = document.createElement('div'); box.className = 'content';
        if(f.exists){ el.onclick = () => showContent(f.path, box, caret); }
        c.appendChild(box);
      }
      if((p.agents||[]).length){
        const an = document.createElement('div'); an.className='note'; an.style.marginTop='12px';
        an.textContent = t().agents_claude_only;
        c.appendChild(an);
      }
      if(p.truncated){
        const w = document.createElement('div'); w.className = 'note';
        w.style.color = 'var(--text)';
        w.textContent = '⚠ ' + t().scan_truncated;
        c.appendChild(w);
      }
      for(const a of (p.agents||[])){
        const el = document.createElement('div'); el.className = 'row clickable';
        const left = document.createElement('span');
        const caret = document.createElement('span'); caret.textContent = '▸ ';
        left.appendChild(caret);
        left.insertAdjacentHTML('beforeend', a.name);
        const descSpan = document.createElement('span'); descSpan.className = 'dim';
        descSpan.textContent = (a.desc||'').slice(0,40);
        el.appendChild(left); el.appendChild(descSpan);
        const box = document.createElement('div'); box.className = 'content';
        el.onclick = () => showContent(a.path, box, caret);
        c.appendChild(el); c.appendChild(box);
      }
      if(!(p.agents||[]).length){
        const note = document.createElement('div'); note.className = 'empty';
        note.innerHTML = `<span>${t().no_subagents}</span>`;
        c.appendChild(note);
      }
    } else {
      c.appendChild(h);
      if(p.known_projects && p.known_projects.length > 1){
        const sel = document.createElement('select');
        sel.style.cssText = 'background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:6px 8px;margin-bottom:10px;font-size:12px;width:100%';
        for(const pr of p.known_projects){
          const opt = document.createElement('option'); opt.value = pr; opt.textContent = pr;
          if(pr === p.project_dir) opt.selected = true;
          sel.appendChild(opt);
        }
        sel.onchange = () => { selectedProject = sel.value; localStorage.setItem('agent-hud-project', sel.value); rerender(); };
        c.appendChild(sel);
      } else {
        const note = document.createElement('div'); note.className = 'note';
        note.textContent = t().project_label + projectLabel(p.project_dir);
        c.appendChild(note);
      }
      if(p.agents){
        const n = document.createElement('div'); n.className = 'note wide'; n.style.marginBottom = '12px';
        n.textContent = t().skills_note;
        c.appendChild(n);
      }
      if(!p.rows.length){
        const e = document.createElement('div'); e.className = 'empty';
        e.innerHTML = `<span>📦</span><span>${t().no_skills}</span>`;
        c.appendChild(e);
      }
      for(const row of p.rows){
        const wrap = document.createElement('div');
        wrap.className = 'section';
        const isPlugin = row.enabled !== null;
        const key = row.name || '__loose__';
        const hasSkills = (row.skills||[]).length > 0;

        // 1행: 스위치 · 이름 · 버전 · 개수 ......... 그룹
        const el = document.createElement('div'); el.className = 'row sec-head';
        const left = document.createElement('span'); left.className = 'sec-left';
        if(isPlugin){
          const sw = document.createElement('span');
          sw.className = 'switch ' + (row.enabled?'sw-on':'sw-off');
          sw.textContent = row.enabled ? t().on : t().off;
          sw.title = row.enabled ? t().plugin_on_tip : t().plugin_off_tip;
          sw.onclick = e => { e.stopPropagation(); toggle(row.name, !row.enabled, sw); };
          left.appendChild(sw);
        }
        const label = document.createElement('span');
        label.className = 'sec-name' + (hasSkills ? ' clickable' : '');
        label.textContent = (hasSkills ? (skillsOpen[key] ? '▾ ' : '▸ ') : '') +
          (isPlugin ? row.name : t().loose_skills);
        label.title = row.source ? t().from + row.source : '';
        left.appendChild(label);
        const right = document.createElement('span'); right.className = 'sec-right';
        for(const g of (row.modes||[])){
          const gtag = document.createElement('span');
          gtag.className = 'tag'; gtag.textContent = t().group_tag(g);
          gtag.title = t().group_tag_tip;
          right.appendChild(gtag);
        }
        el.appendChild(left); el.appendChild(right);
        if(hasSkills){
          el.classList.add('clickable');
          el.onclick = e => { if(!e.target.closest('.switch,.share,.tag')) { skillsOpen[key] = !skillsOpen[key]; rerender(); } };
        }
        wrap.appendChild(el);

        // 2행: 뱃지 ......... 체크박스. 폭이 좁아지면 이 줄 안에서만 접힌다.
        const meta = document.createElement('div'); meta.className = 'sec-meta';
        const badges = document.createElement('span'); badges.className = 'badges';
        if(isPlugin){
          const v = document.createElement('span'); v.className='tag'; v.textContent = 'v' + row.version;
          badges.appendChild(v);
        }
        if(hasSkills){
          const c = document.createElement('span'); c.className='tag';
          c.textContent = t().skills_count(row.skills.length);
          badges.appendChild(c);
        }
        for(const a of (p.agents||[])){
          const tag = document.createElement('span');
          tag.className = 'agenttag ' + ((row.section_agents||[]).includes(a) ? 'yes' : 'no');
          tag.textContent = shortAgent(a);
          badges.appendChild(tag);
        }
        meta.appendChild(badges);
        const secMiss = (p.agents||[]).filter(a => !(row.section_agents||[]).includes(a));
        const ids = (row.skills||[]).filter(x => x.linkable).map(x => x.id);
        if(ids.length){
          const share = document.createElement('label');
          share.className = 'share' + (secMiss.length ? '' : ' share-done');
          const cb = document.createElement('input'); cb.type = 'checkbox';
          cb.checked = (row.skills||[]).every(x => x.shared);
          cb.onclick = e => { e.stopPropagation(); linkSkill(ids, cb.checked, share); };
          share.appendChild(cb);
          share.appendChild(document.createTextNode(
            secMiss.length ? t().share_to(secMiss.map(shortAgent)) : t().share_done));
          share.title = t().share_all_tip;
          meta.appendChild(share);
        }
        wrap.appendChild(meta);

        if(skillsOpen[key]){
          if(hasSkills){
            for(const s of row.skills){
              const srow = document.createElement('div'); srow.className = 'row sub skill-row';
              const ssw = document.createElement('span');
              ssw.className = 'switch ' + (s.blocked ? 'sw-off' : 'sw-on');
              ssw.textContent = s.blocked ? t().blocked : t().allowed;
              ssw.title = s.blocked ? t().blocked_tip : t().allowed_tip;
              if(isPlugin){ ssw.onclick = () => toggleSkill(row.name, s.id, !s.blocked, ssw); }
              else { ssw.className = 'switch sw-on'; ssw.textContent = t().allowed; }

              const stext = document.createElement('div'); stext.className = 'skill-text';
              const sname = document.createElement('div'); sname.className = 'skill-name';
              sname.textContent = s.name;
              const full = s.desc||'';
              const sdesc = document.createElement('div'); sdesc.className = 'dim skill-desc';
              sdesc.textContent = full;
              stext.appendChild(sname); stext.appendChild(sdesc);

              // 섹션과 같으면 아무것도 안 그린다. 같은 사실을 줄마다 되풀이하지 않는다.
              const badges = document.createElement('span');
              const sec = (row.section_agents||[]).join('|');
              if((s.agents||[]).join('|') !== sec){
                for(const a of (p.agents||[])){
                  const tag = document.createElement('span');
                  tag.className = 'agenttag ' + ((s.agents||[]).includes(a) ? 'yes' : 'no');
                  tag.textContent = a;
                  badges.appendChild(tag);
                }
              }
              srow.appendChild(ssw); srow.appendChild(stext); srow.appendChild(badges);
              if(s.linkable){
                // 섹션과 같은 말이면 글자를 반복하지 않는다. 뱃지와 같은 규칙.
                const miss = (s.missing||[]).map(shortAgent);
                const sameAsSection = (s.agents||[]).join('|') === (row.section_agents||[]).join('|');
                const share = document.createElement('label');
                share.className = 'share' + (miss.length ? '' : ' share-done');
                const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = !!s.shared;
                cb.onclick = e => { e.stopPropagation(); linkSkill(s.id, cb.checked, share); };
                share.appendChild(cb);
                if(!sameAsSection){
                  share.appendChild(document.createTextNode(miss.length ? t().share_to(miss) : t().share_done));
                }
                share.title = miss.length ? t().share_to(miss) : t().share_done;
                srow.appendChild(share);
              }
              wrap.appendChild(srow);
              if(full.length > 40){
                sdesc.classList.add('clickable');
                sdesc.title = t().read_full_tip;
                const dbox = document.createElement('div'); dbox.className = 'content';
                dbox.textContent = full;
                sdesc.onclick = (e) => {
                  e.stopPropagation();
                  const opening = !dbox.classList.contains('open');
                  dbox.classList.toggle('open');
                  polling = !opening;
                  if(!opening) tick();
                };
                wrap.appendChild(dbox);
              }
            }
          } else {
            const note = document.createElement('div'); note.className = 'note sub';
            note.textContent = t().no_skills_found;
            wrap.appendChild(note);
          }
        }
        c.appendChild(wrap);
      }
    }
    app.appendChild(c);
  }
  const pr = d.proc || {};
  document.getElementById('tsText').textContent = t().updated + new Date(d.ts*1000).toLocaleTimeString() +
    (pr.mb ? ` · ${t().usage(pr.mb, pr.cpu)}` : '');
}

// 갱신 주기는 사용자가 정한다. 3초는 켜두고 보는 화면에는 과할 수 있고,
// 파일을 계속 읽는 일이라 조용히 두고 싶을 때도 있다.
const PERIODS = [1, 3, 10, 30, 60, 0];
let period = +(localStorage.getItem('agent-hud-period') ?? 3);
let timer = null;
function applyPeriod(){
  if(timer) clearInterval(timer);
  timer = period > 0 ? setInterval(tick, period * 1000) : null;
}
function renderPeriod(){
  const sel = document.getElementById('period');
  sel.innerHTML = '';
  for(const p of PERIODS){
    const o = document.createElement('option');
    o.value = p; o.textContent = p ? t().every_n(p) : t().paused;
    if(p === period) o.selected = true;
    sel.appendChild(o);
  }
  sel.title = t().period_tip;
}
document.getElementById('period').onchange = e => {
  period = +e.target.value;
  localStorage.setItem('agent-hud-period', period);
  applyPeriod();
  if(period > 0) tick();
};
renderPeriod();
tick(); applyPeriod();
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs, unquote
        if self.path.startswith("/api/state"):
            qs = parse_qs(urlparse(self.path).query)
            proj = unquote((qs.get("project") or [""])[0]) or None
            self._send_json(build_state(proj))
        elif self.path.startswith("/api/content"):
            qs = parse_qs(urlparse(self.path).query)
            path = unquote((qs.get("path") or [""])[0])
            build_state()  # ensure READABLE_PATHS is fresh before checking
            text, err = read_content(path)
            if text is None:
                self._send_json({"ok": False, "error": err}, 403)
            else:
                self._send_json({"ok": True, "text": text})
        else:
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        if self.path == "/api/toggle":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send_json({"ok": False, "error": "bad request"}, 400)
            ok, err = toggle_plugin(payload.get("name", ""), bool(payload.get("enable")))
            self._send_json({"ok": ok, "error": err})
        elif self.path == "/api/group":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send_json({"ok": False, "error": "bad request"}, 400)
            ok, err = modify_group(payload.get("action", ""), payload.get("group", ""), payload.get("plugin", ""))
            self._send_json({"ok": ok, "error": err})
        elif self.path == "/api/activate":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send_json({"ok": False, "error": "bad request"}, 400)
            ok, err = activate_group(payload.get("group", ""))
            self._send_json({"ok": ok, "error": err})
        elif self.path == "/api/linkskill":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send_json({"ok": False, "error": "bad request"}, 400)
            project = payload.get("project", "") or PROJECT_DIR
            if project not in known_projects():
                return self._send_json({"ok": False, "error": "unknown project"}, 400)
            names = payload.get("names") or [payload.get("name", "")]
            on = bool(payload.get("on"))
            errs = []
            for n in names:
                ok, err = link_skill(n, on, project)
                if not ok:
                    errs.append(f"{n}: {err}")
            self._send_json({"ok": not errs, "error": "; ".join(errs[:3])})
        elif self.path == "/api/skill":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send_json({"ok": False, "error": "bad request"}, 400)
            ok, err = modify_skill_permission(
                payload.get("action", ""), payload.get("plugin", ""),
                payload.get("skill", ""), payload.get("project", ""),
            )
            self._send_json({"ok": ok, "error": err})
        elif self.path == "/api/register":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send_json({"ok": False, "error": "bad request"}, 400)
            path = payload.get("path", "")
            if path and os.path.isdir(path):
                register_project(path)
                self._send_json({"ok": True})
            else:
                self._send_json({"ok": False, "error": "directory not found"}, 400)
        else:
            self._send_json({"ok": False, "error": "not found"}, 404)


def port_alive(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def main():
    if os.environ.get("CLAUDE_HUD_DISABLE") == "1":
        return
    global PROJECT_DIR
    if len(sys.argv) > 2 and sys.argv[1] == "--register":
        PROJECT_DIR = os.path.abspath(sys.argv[2])

    base_port = 7717
    if os.path.exists(PORT_FILE) and port_alive(int(open(PORT_FILE).read().strip() or 0)):
        # already running: just register this project (if any) and exit, no new server/tab
        port = int(open(PORT_FILE).read().strip())
        try:
            import urllib.request
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/register",
                data=json.dumps({"path": PROJECT_DIR}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass
        return

    register_project(PROJECT_DIR)
    port = base_port
    for _ in range(10):
        if not port_alive(port):
            break
        port += 1
    with open(PORT_FILE, "w") as f:
        f.write(str(port))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    threading.Thread(target=_update_check_loop, daemon=True).start()
    webbrowser.open(f"http://127.0.0.1:{port}", new=0, autoraise=False)
    # keep process alive in background; parent hook detaches us
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
