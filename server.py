#!/usr/bin/env python3
"""Agent HUD: live status dashboard for a local Claude Code setup.

Extensibility: add a new panel by writing one function of shape
    def collect_x(ctx) -> dict   and appending it to PANELS.
Add a new plugin group by editing modes.json, or via the "+" button in the
dashboard UI itself — no code change needed either way.
"""
import json, os, re, socket, http.server, socketserver, threading, webbrowser, sys, time, subprocess, shutil, resource

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
# 기본값은 스크립트 옆이다 -- 저장소에서 바로 실행하거나 install.sh로 복사해 쓰는 경우.
# AGENT_HUD_HOME으로 옮길 수 있다. 패키지 매니저로 설치하면 코드가 업그레이드마다 통째로
# 갈리는 곳에 놓이므로, 사용자 데이터를 거기 두면 그룹과 프로젝트 목록이 날아간다.
TOOL_DIR = os.environ.get("AGENT_HUD_HOME") or os.path.dirname(os.path.abspath(__file__))
os.makedirs(TOOL_DIR, exist_ok=True)
PORT_FILE = os.path.join(TOOL_DIR, ".port")
PROJECTS_FILE = os.path.join(TOOL_DIR, "projects.json")
MODES_FILE = os.path.join(TOOL_DIR, "modes.json")
PROJECT_DIR = os.getcwd()  # fallback: cwd of whichever invocation started this process

VERSION = "0.1.0"
UPDATE_REPO = "ganggangstone/agent-hud"
UPDATE_CACHE_FILE = os.path.join(TOOL_DIR, ".update_check.json")
UPDATE_CHECK_INTERVAL_SEC = 12 * 60 * 60


def remember_project(path):
    """이미 아는 프로젝트면 아무것도 하지 않는다. 발견할 때마다 시각을 갱신하면
    자동 발견된 폴더가 매번 목록 맨 위로 올라온다."""
    if path in ("/", HOME):
        return
    projects = read_json(PROJECTS_FILE, {})
    if path in projects:
        return
    projects[path] = time.time() - 86400        # 직접 연 프로젝트보다 뒤에 놓는다
    try:
        with open(PROJECTS_FILE, "w") as f:
            json.dump(projects, f)
    except Exception:
        pass


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
    if os.path.isdir(path):
        remove_stale_skill_denies(path)


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
    enabled, has_local = plugin_state(project_dir)
    installed = known_plugin_names()
    sets = read_sets()
    assigned = read_json(SETS_FILE, {}).get(project_dir, "")
    sources = skill_sources(project_dir)
    groups = []
    for gname, entry in sets.items():
        plugins = [m for m in entry["plugins"] if m in installed]
        skills = [sk for sk in entry["skills"] if sk in sources]
        groups.append({
            "name": gname,
            "assigned": gname == assigned,
            "members": [{"name": m, "kind": "plugin", "on": bool(enabled.get(m, False))} for m in plugins]
                     + [{"name": sk, "kind": "skill", "on": skill_is_shared(project_dir, sk)} for sk in skills],
        })
    return {"title": "Groups", "groups": groups,
            "all_plugins": sorted(installed), "all_skills": sorted(sources),
            "assigned": assigned, "project_dir": project_dir, "known_projects": known_projects()}


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


# 공개 명세(agentskills.io/specification)가 정한 제약. 어기면 도구가 스킬을 무시할 수
# 있지만 **위반이 곧 로드 실패는 아니다** — 상한을 넘고도 잘 읽히는 스킬을 실제로 봤다.
# 그래서 화면에서도 "안 읽힘"이 아니라 "명세 위반"이라고 부른다.
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DESC_MAX = 1024


def _skill_meta(path, folder):
    """SKILL.md를 한 번 읽어 (표시 이름, 설명, 명세 위반 목록)."""
    name, desc, issues = folder, "", []
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(8000)
    except Exception:
        return name, desc, [{"code": "unreadable"}]
    if not head.startswith("---"):
        return name, desc, [{"code": "no_frontmatter"}]
    declared = None
    lines = head.split("---", 2)[1].splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("name:"):
            declared = line.split(":", 1)[1].strip().strip('"\'')
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
            desc = rest.strip('"\'')
        i += 1
    if declared:
        name = declared
        if not SKILL_NAME_RE.match(declared) or len(declared) > 64:
            issues.append({"code": "name_format", "name": declared})
        elif declared != folder:
            issues.append({"code": "name_mismatch", "name": declared, "folder": folder})
    else:
        issues.append({"code": "name_missing"})
    if not desc.strip():
        issues.append({"code": "desc_missing"})
    elif len(desc) > DESC_MAX:
        issues.append({"code": "desc_long", "len": len(desc)})
    return name, desc, issues


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
        name, desc, issues = _skill_meta(os.path.join(path, "SKILL.md"), sid)
        out.append({"id": sid, "name": name, "desc": desc, "path": path, "issues": issues})
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


PROJECT_MARKERS = [
    os.path.join(".claude", "skills"), os.path.join(".claude", "agents"),
    os.path.join(".claude", "settings.json"), os.path.join(".claude", "settings.local.json"),
    os.path.join(".agents", "skills"), os.path.join(".cursor", "skills"),
    os.path.join(".codex", "skills"), os.path.join(".github", "skills"),
    os.path.join(".gemini", "skills"),
]


def _scan_tree(project_dir):
    """project_dir 아래 전체에서 지침 파일과 하위 프로젝트를 찾는다.
    -> (행 목록, 잘렸는지, 하위 프로젝트 경로)"""
    rows, dirs, truncated, subprojects = [], 0, False, []
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
        if cur != project_dir and any(os.path.exists(os.path.join(cur, mk)) for mk in PROJECT_MARKERS):
            subprojects.append(cur)             # 자기 .claude/ 를 가진 폴더 = 별개 프로젝트
        for rel, tool in _DIR_SOURCES:          # .cursor/rules/ 같은 디렉터리형 (점 폴더라 위 가지치기에 걸린다)
            d = os.path.join(cur, rel.replace("/", os.sep).rstrip(os.sep))
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if fn.endswith(RULE_EXTS):
                    rows.append(_file_row(prefix + rel + fn, os.path.join(d, fn), tool))
    return rows, truncated, subprojects


def _instruction_rows(project_dir):
    """전체 트리를 훑되 결과는 잠깐 재사용한다 (폴링이 3초라 매번 훑을 이유가 없다)."""
    now = time.time()
    hit = _scan_cache.get(project_dir)
    if hit and now - hit[0] < SCAN_TTL:
        return hit[1]
    rows, truncated, subprojects = _scan_tree(project_dir)
    rows = [r for r in rows if r["name"] != "CLAUDE.md"]  # 루트 것은 위쪽 고정 행이 보여준다
    for sub in subprojects:
        remember_project(sub)                   # 목록에 올려두면 골라서 볼 수 있다
    _scan_cache[project_dir] = (now, (rows, truncated))
    return rows, truncated


# 스킬은 SKILL.md 형식이 공개 표준(agentskills.io)이라 폴더째 이식된다. 그런데 명세는
# **탐색 경로를 정하지 않아서**, 어디에 두느냐가 곧 어느 에이전트가 보느냐가 된다.
# Claude Code만 `.agents/skills`를 읽지 않는다는 게 이 표의 요점이다.
# 출처(2026-09 공식 문서): code.claude.com/docs/en/skills,
# learn.chatgpt.com/docs/build-skills, cursor.com/docs/context/skills,
# code.visualstudio.com/docs/copilot/customization/agent-skills, geminicli.com/docs/cli/skills
# Antigravity(agy)는 CLI에 들어 있는 문서와 2026-09 센티널 실측으로 확인했다(ADR 10).
SKILL_AGENTS = ["Claude Code", "Codex", "Cursor", "Copilot", "Gemini CLI", "Antigravity"]

SKILL_ROOTS_PROJECT = [
    (".claude/skills", ["Claude Code", "Cursor", "Copilot"]),
    (".agents/skills", ["Codex", "Cursor", "Copilot", "Gemini CLI", "Antigravity"]),
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
    (".gemini/config/skills", ["Antigravity"]),  # agy는 ~/.agents/skills를 읽지 않는다
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


# 플러그인은 스킬만 담지 않는다. 공식 문서 기준 구성 요소와, 그중 무엇이 다른 에이전트로
# 갈 수 있는지. 체크박스는 스킬만 옮기므로 나머지가 있으면 화면이 그 사실을 말해야 한다.
# 출처: code.claude.com/docs/en/plugins (Plugin structure overview)
PLUGIN_PARTS = [
    # (경로, 이름, 다른 에이전트로 가나)
    ("agents", "agents", True),          # Cursor·Copilot이 .claude/agents를 읽는다
    (".mcp.json", "mcp", True),          # MCP는 공통 규격, 설정 위치만 다르다
    ("commands", "commands", False),
    ("hooks", "hooks", False),
    (".lsp.json", "lsp", False),
    ("monitors", "monitors", False),
    ("bin", "bin", False),
    ("settings.json", "settings", False),
]


def plugin_components(install_path):
    """스킬 말고 이 플러그인에 또 뭐가 들어 있나. 개수까지 센다 -- '커맨드'만 있으면
    하나인지 스무 개인지 알 수 없다."""
    if not install_path:
        return []
    out = []
    for rel, name, portable in PLUGIN_PARTS:
        path = os.path.join(install_path, rel)
        if not os.path.exists(path):
            continue
        if os.path.isdir(path):
            n = sum(1 for f in os.listdir(path) if not f.startswith("."))
        else:
            n = 1          # .mcp.json 처럼 파일 하나로 된 것
        if n:
            out.append({"name": name, "portable": portable, "n": n})
    return out


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


def _loaded_count(rows):
    """이 프로젝트에서 Claude Code가 실제로 읽는 스킬 수.

    스킬은 본문이 아니라 **이름과 설명이 세션 시작 때 전부** 컨텍스트에 올라간다
    (agentskills.io 명세의 progressive disclosure). 그래서 안 쓰는 스킬도 비용이다.
    꺼진 플러그인의 스킬은 빠진다. permissions.deny로 차단한 스킬은 목록에 남으므로
    빼지 않는다(센티널 실측, ADR 10).
    """
    n = 0
    for row in rows:
        if row["enabled"] is False:          # 꺼진 플러그인
            continue
        for sk in row["skills"]:
            if "Claude Code" in (sk.get("agents") or []):
                n += 1
    return n


def _section_state(skills):
    """에이전트별로 all / some / none. 교집합만 쓰면 12개 중 3개가 막혔을 때
    나머지 9개가 멀쩡한데도 섹션 전체가 '못 봄'으로 보인다."""
    sets = [set(sk["agents"]) for sk in skills]
    out = {}
    for a in SKILL_AGENTS:
        n = sum(1 for x in sets if a in x)
        out[a] = "all" if sets and n == len(sets) else ("some" if n else "none")
    return out


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
    enabled, has_local = plugin_state(project_dir)
    installed = read_json(os.path.join(CLAUDE_DIR, "plugins", "installed_plugins.json")).get("plugins", {})
    marketplaces = read_json(os.path.join(CLAUDE_DIR, "plugins", "known_marketplaces.json"))
    modes = read_json(MODES_FILE)

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
        rows.append({
            "name": name,
            "section_state": _section_state(skills),
            "components": plugin_components(install_path),
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
        name, desc, issues = _skill_meta(hit["path"], sid)
        loose.append(decorate({"id": sid, "name": name, "desc": desc, "issues": issues,
                               "path": os.path.dirname(hit["path"])}, []))
    if loose:
        rows.append({
            "name": "", "version": "", "enabled": None, "claude_only": False,
            "section_state": _section_state(loose),
            "modes": [], "source": ", ".join(sorted({r for sk in loose for r in sk["roots"]})),
            "skills": loose,
        })

    return {
        "title": "Skills (who can see them)",
        "rows": rows,
        "agents": SKILL_AGENTS,
        "loaded": _loaded_count(rows),
        "has_local": has_local,
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


# 플러그인 on/off는 프로젝트 단위다. `claude plugin enable`은 사용자 전역 파일에 쓰므로
# 쓰지 않는다 -- `enabledPlugins`는 어느 설정 파일에나 넣을 수 있고(공식 문서 "Any file"),
# 프로젝트 값이 전역을 이긴다. 실측으로 확인했다(ADR 10 덧4).
# 쓰는 곳은 `settings.local.json` -- Claude Code가 만드는 개인용 파일이고 커밋되지 않는다.
LOCAL_SETTINGS = os.path.join(".claude", "settings.local.json")


def plugin_state(project_dir):
    """이 프로젝트에서 실제로 적용되는 플러그인 on/off. -> (상태, 이 프로젝트가 직접 정했나)"""
    user = read_json(os.path.join(CLAUDE_DIR, "settings.json")).get("enabledPlugins", {})
    shared = read_json(os.path.join(project_dir, ".claude", "settings.json")).get("enabledPlugins", {})
    local = read_json(os.path.join(project_dir, LOCAL_SETTINGS)).get("enabledPlugins", {})
    return {**user, **shared, **local}, bool(local)   # 로컬 > 프로젝트 공유 > 사용자


def set_plugins(changes, project_dir):
    """{플러그인: bool}을 이 프로젝트의 settings.local.json에 병합한다."""
    if not project_dir or not os.path.isdir(project_dir):
        return False, "project not found"
    known = known_plugin_names()
    unknown = [n for n in changes if n not in known]
    if unknown:
        return False, "unknown plugin: " + ", ".join(unknown[:3])
    path = os.path.join(project_dir, LOCAL_SETTINGS)
    data = read_json(path, {})
    data.setdefault("enabledPlugins", {}).update({k: bool(v) for k, v in changes.items()})
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return False, str(e)
    return True, ""


# 세트는 함께 쓰는 플러그인과 스킬의 묶음이다. 옛 modes.json은 {이름: [플러그인]} 이었고
# 지금은 {이름: {"plugins": [...], "skills": [...]}} 다. 옛 파일도 그대로 읽는다.
SETS_FILE = os.path.join(TOOL_DIR, "project-sets.json")  # {프로젝트: 세트 이름}


def read_sets():
    raw = read_json(MODES_FILE, {})
    out = {}
    for name, v in raw.items():
        if isinstance(v, list):
            out[name] = {"plugins": list(v), "skills": []}
        else:
            out[name] = {"plugins": list(v.get("plugins", [])), "skills": list(v.get("skills", []))}
    return out


def write_sets(sets):
    try:
        with open(MODES_FILE, "w") as f:
            json.dump(sets, f, ensure_ascii=False, indent=2)
        return True, ""
    except Exception as e:
        return False, str(e)


def modify_group(action, group, member, kind="plugin"):
    group = (group or "").strip()
    if not group:
        return False, "set name required"
    key = "skills" if kind == "skill" else "plugins"
    if kind == "plugin" and member not in known_plugin_names():
        return False, "unknown plugin"
    if kind == "skill" and member not in skill_sources(PROJECT_DIR):
        return False, "unknown skill"
    sets = read_sets()
    if action == "add":
        entry = sets.setdefault(group, {"plugins": [], "skills": []})
        if member not in entry[key]:
            entry[key].append(member)
    elif action == "remove":
        entry = sets.get(group)
        if entry and member in entry[key]:
            entry[key].remove(member)
            if not entry["plugins"] and not entry["skills"]:
                del sets[group]
    else:
        return False, "unknown action"
    return write_sets(sets)


def assign_set(name, project_dir):
    """세트를 프로젝트에 적용한다. 스킬 링크도 플러그인 on/off도 이 프로젝트에만 걸린다
    (플러그인은 settings.local.json의 enabledPlugins에 쓴다).
    name이 빈 문자열이면 이 프로젝트의 배정을 푼다."""
    if not project_dir or not os.path.isdir(project_dir):
        return False, "project not found"
    sets = read_sets()
    if name and name not in sets:
        return False, "unknown set"

    # 1) 스킬: 이 세트 것만 남긴다. 어느 세트에도 없는 스킬 링크는 사용자가 직접 건 것이므로 둔다.
    wanted = set(sets.get(name, {}).get("skills", [])) if name else set()
    managed = {sk for v in sets.values() for sk in v["skills"]}
    errors = []
    for sk in sorted(managed):
        ok, err = link_skill(sk, sk in wanted, project_dir)
        if not ok and sk in wanted:
            errors.append(f"{sk}: {err}")

    # 2) 플러그인: 세트를 배정하지 않을 때는 건드리지 않는다.
    if name:
        # 설치된 플러그인 전부에 값을 적는다. 하나라도 빠뜨리면 그건 전역 값을 물려받아
        # "왜 이게 켜져 있지"가 된다.
        members = set(sets[name]["plugins"])
        ok, err = set_plugins({pl: pl in members for pl in known_plugin_names()}, project_dir)
        if not ok:
            errors.append(err)

    assigned = read_json(SETS_FILE, {})
    if name:
        assigned[project_dir] = name
    else:
        assigned.pop(project_dir, None)
    try:
        with open(SETS_FILE, "w") as f:
            json.dump(assigned, f, ensure_ascii=False, indent=2)
    except Exception as e:
        errors.append(str(e))
    return (not errors), "; ".join(errors)[:300]


SHARED_SETTINGS = os.path.join(".claude", "settings.json")

# 예전 버전은 스킬 차단을 Skill(플러그인@마켓플레이스:스킬)로 썼다. Claude Code는 스킬 이름에 @를 쓰지 않아
# 이 항목은 목록에서도 빠지지 않고 호출도 막지 못했다(센티널 실측, ADR 10). 그 형식만 골라 지운다.
_STALE_SKILL_DENY = re.compile(r"^Skill\([^()@:]+@[^()@:]+:[^()]+\)$")


def remove_stale_skill_denies(project_dir):
    """이 프로젝트 설정에서 효과 없던 스킬 차단 항목을 지우고, 지운 항목을 돌려준다.
    지울 게 없는 파일은 다시 쓰지 않는다."""
    removed = []
    for rel in (LOCAL_SETTINGS, SHARED_SETTINGS):
        path = os.path.join(project_dir, rel)
        if not os.path.isfile(path):
            continue
        settings = read_json(path, {})
        if not isinstance(settings, dict):
            continue
        perms = settings.get("permissions")
        deny = perms.get("deny") if isinstance(perms, dict) else None
        if not isinstance(deny, list):
            continue
        stale = [e for e in deny if isinstance(e, str) and _STALE_SKILL_DENY.match(e)]
        if not stale:
            continue
        perms["deny"] = [e for e in deny if e not in stale]
        if not perms["deny"]:
            perms.pop("deny")
        if not perms:
            settings.pop("permissions")
        try:
            with open(path, "w") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"agent-hud: {path} 정리 실패: {e}", file=sys.stderr)
            continue
        removed += stale
        print(f"agent-hud: {path}에서 효과 없는 스킬 차단 {len(stale)}개 삭제: {', '.join(stale)}", file=sys.stderr)
    return removed


def cleanup_known_projects():
    for project_dir in known_projects():
        remove_stale_skill_denies(project_dir)


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
h1{margin:0;font-size:23px;font-weight:800;letter-spacing:-.02em;line-height:1.1;color:var(--text)}
#h1sub{display:block;margin-top:4px;font-size:10px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--dim);opacity:.7;font-family:ui-monospace,"SF Mono",Menlo,monospace}
.rule-note{border-left:2px solid var(--border);padding:2px 0 2px 10px;margin-bottom:14px;
  color:var(--dim);font-size:12px;line-height:1.6}
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
.note{color:var(--dim);font-size:12px;margin-top:6px;line-height:1.65;text-wrap:pretty}
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
.agenttag.partial{color:var(--dim);text-decoration:underline dotted;text-underline-offset:2px;cursor:help}
.loadline{font-size:13px;color:var(--text);background:var(--off-tint);border:1px solid var(--border);
  border-radius:6px;padding:8px 11px;margin:2px 0 10px;cursor:help;line-height:1.6}
.loadline b{font-weight:700}
.warn{margin-left:8px;padding:1px 7px;border-radius:4px;font-size:10.5px;font-weight:600;
  background:var(--off-tint);color:var(--text);cursor:help;white-space:nowrap;vertical-align:middle}
.comp{color:var(--dim);font-size:11px;white-space:nowrap;cursor:help;
  font-family:ui-monospace,"SF Mono",Menlo,monospace;border-bottom:1px dotted var(--border)}
.comp:hover{color:var(--text);border-bottom-color:var(--dim)}
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
    <h1>Agent HUD</h1>
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
    title_groups: 'Groups', title_instructions: 'Agent instructions', title_skills: 'Plugins & skills',
  skills_note: 'Everything on this tab applies to the selected project only.',
  badge_off_tip: a => `${a} cannot see this skill`,
  badge_on_tip: a => `${a} can use this skill`,
  no_skills: 'No skills found in any known folder.',
  link_failed: 'Could not share that skill: ',
  loose_skills: 'Skills not from a plugin',
    set_count: (pl, sk) => `${pl} plugin${pl===1?'':'s'} · ${sk} skill${sk===1?'':'s'}`,
    set_apply: 'Apply to this project', set_applied: 'Applied to this project',
    set_apply_tip: 'Applies to this project only. Other projects are untouched.',
    assign_confirm: (g, p, pl, sk) => `Apply group "${g}" to this project?\n\n${p}\n\n${sk} skills are linked here.\nPlugins on: ${pl}\nEvery other plugin is turned off, in this project only.`,
    unassign_confirm: (g, p) => `Stop using "${g}" here?\n\n${p}\n\nIts skill links are removed. Plugins stay as they are.`,
    kind_plugin: 'plugin', kind_skill: 'skill',
    add_member_ph: '+ add a plugin or skill…',
    member_plugin_tip: 'On in this project',
    member_skill_tip: 'Linked into this project',
    assign_failed: 'Could not apply that group: ',
    on: 'ON', off: 'OFF',
    remove: 'remove ✕', remove_tip: (m,g) => `take ${m} out of "${g}"`,
    remove_confirm: (m,g) => `Remove ${m} from group "${g}"?`,
    new_group: '+ create a new group', new_group_tip: 'Plugins you switch on together. For example one set for coding, one for video work',
    new_group_name_prompt: 'Name for the new group (e.g. "dev", "video"):',
    new_group_first_prompt: 'Which plugin should it start with?\n',
    groups_legend: 'The plugins and skills you use together. Applying one sets up that project and leaves the others alone.',
  not_found: 'not found',
  agents_note: '.claude/agents/*.md · Cursor and Copilot read the same folder',
  comp: {agents: 'agents', mcp: 'MCP', commands: 'commands', hooks: 'hooks', lsp: 'LSP',
    monitors: 'monitors', bin: 'binaries', settings: 'settings'},
  comp_count: (label, n) => `${n} ${label}`,
  comp_portable_tip: n => `This plugin ships ${n}. The checkbox moves skills only`,
  comp_stays_tip: n => `This plugin ships ${n}. They work wherever the plugin is on; the checkbox moves skills only`,
  share_to: names => 'apply to ' + names.join(', '),
  share_done: 'applied everywhere',
  share_all_tip: 'Applies this skill to those agents in this project. Links it into the folders it is missing from; the original never moves.',
  partly: 'Some skills only',
  inherited_note: 'Nothing set for this project yet, using defaults',
  add_project: '+ add a folder', add_project_tip: 'Any folder. It does not have to be a git repository',
  add_project_prompt: 'Full path of the folder to add:',
  add_project_failed: 'Could not add that folder: ',
  no_project_yet: 'no folders yet',
  loaded: (n, tok) => `This project loads <b>${n} skills</b> (about <b>${tok.toLocaleString()} tokens</b> every session)`,
  loaded_tip: 'A skill\u2019s name and description are loaded at startup for every available skill, whether you use it or not. The spec puts that at about 100 tokens each; the real figure depends on how long the descriptions are.',
  spec_issue: 'spec',
  issue: {
    unreadable: () => 'SKILL.md could not be read',
    no_frontmatter: () => 'No YAML frontmatter',
    name_missing: () => 'name is missing',
    name_format: i => `name "${i.name}" — lowercase letters, digits and single hyphens only, max 64`,
    name_mismatch: i => `name "${i.name}" does not match its folder "${i.folder}"`,
    desc_missing: () => 'description is missing',
    desc_long: i => `description is ${i.len} characters (limit 1024)`,
  },
  scan_truncated: 'This project is large, so the scan stopped early. Some instruction files further down may be missing.',
    no_subagents: 'No subagents',
    loading: 'loading…', error: 'error: ',
    toggle_failed: 'Could not switch that plugin: ', group_update_failed: 'Could not change the group: ',
    plugin_on_tip: 'On in this project. Click to turn it off (next session)',
    plugin_off_tip: 'Off in this project. Click to turn it on (next session)',
    skills_count: n => n + (n === 1 ? ' skill' : ' skills'),
    group_tag: g => 'group: ' + g, group_tag_tip: 'Manage groups in the Groups tab',
    from: 'from: ',
    read_full_tip: 'Read the full description',
    no_skills_found: 'No skills',
    updated: 'updated ', every_n: n => `every ${n}s`, paused: 'paused',
    usage: (mb, cpu) => `${mb}MB` + (cpu === null ? '' : ` · ${cpu}% CPU`),
    period_tip: 'How often this page re-reads the files',
    switching: 'switching…',
    update_available: (v, latest, repo) => `↑ v${latest} available (you're on v${v}) — <a href="https://github.com/${repo}/releases/latest" target="_blank" rel="noopener">see release</a>, then <code>git pull</code> in your clone and run <code>./install.sh</code> (Homebrew: <code>brew upgrade agent-hud</code>)`,
    feedback_open: 'send feedback ↗',
  },
  ko: {
    banner: '플러그인은 <b>다음 세션부터</b>, 나머지는 바로 반영됩니다.',
    tagline: '로컬 대시보드',
    title_groups: '그룹', title_instructions: '에이전트 지침', title_skills: '플러그인 & 스킬',
  skills_note: '이 탭의 조작은 선택한 프로젝트에만 적용됩니다.',
  badge_off_tip: a => `${a}는 이 스킬을 못 봅니다`,
  badge_on_tip: a => `${a}가 이 스킬을 씁니다`,
  no_skills: '어느 폴더에서도 스킬을 못 찾았습니다.',
  link_failed: '스킬을 넣지 못했습니다: ',
  loose_skills: '플러그인 밖의 스킬',
    set_count: (pl, sk) => `플러그인 ${pl} · 스킬 ${sk}`,
    set_apply: '이 프로젝트에 적용', set_applied: '이 프로젝트에 적용됨',
    set_apply_tip: '이 프로젝트에만 적용됩니다. 다른 프로젝트는 그대로입니다.',
    assign_confirm: (g, p, pl, sk) => `"${g}" 그룹을 이 프로젝트에 적용할까요?\n\n${p}\n\n스킬 ${sk}개가 여기 걸립니다.\n켜지는 플러그인: ${pl}\n나머지 플러그인은 꺼집니다. 이 프로젝트에서만요.`,
    unassign_confirm: (g, p) => `"${g}" 적용을 풀까요?\n\n${p}\n\n스킬 링크만 지웁니다. 플러그인은 그대로 둡니다.`,
    kind_plugin: '플러그인', kind_skill: '스킬',
    add_member_ph: '+ 플러그인 또는 스킬 추가…',
    member_plugin_tip: '이 프로젝트에서 켜짐',
    member_skill_tip: '이 프로젝트에 걸려 있음',
    assign_failed: '그룹을 적용하지 못했습니다: ',
    on: '켜짐', off: '꺼짐',
    remove: '빼기 ✕', remove_tip: (m,g) => `"${g}" 그룹에서 ${m} 빼기`,
    remove_confirm: (m,g) => `"${g}" 그룹에서 ${m} 뺄까요?`,
    new_group: '+ 새 그룹 만들기', new_group_tip: '함께 쓰는 플러그인과 스킬을 묶어둡니다. 예를 들어 개발용, 영상제작용',
    new_group_name_prompt: '새 그룹 이름 (예: "개발", "영상제작"):',
    new_group_first_prompt: '어떤 플러그인부터 넣을까요?\n',
    groups_legend: '함께 쓰는 플러그인과 스킬을 묶어둔 것입니다. 프로젝트에 적용하면 그 프로젝트만 바뀌고 나머지는 그대로입니다.',
  not_found: '없음',
  agents_note: '.claude/agents/*.md · Cursor와 Copilot도 같은 폴더를 읽습니다',
  comp: {agents: '서브에이전트', mcp: 'MCP', commands: '커맨드', hooks: '훅', lsp: 'LSP',
    monitors: '모니터', bin: '실행파일', settings: '기본설정'},
  comp_count: (label, n) => `${label} ${n}개`,
  comp_portable_tip: n => `이 플러그인에 ${n}이(가) 들어 있습니다. 체크박스는 스킬만 옮깁니다`,
  comp_stays_tip: n => `이 플러그인에 ${n}이(가) 들어 있습니다. 플러그인을 켠 에이전트에서만 동작하고, 체크박스는 스킬만 옮깁니다`,
  share_to: names => names.join('·') + '에도 적용하기',
  share_done: '전부 적용됨',
  share_all_tip: '이 프로젝트에서 그 에이전트들에도 이 스킬을 적용합니다. 빠져 있는 폴더에만 링크를 채우고, 원본은 움직이지 않습니다.',
  partly: '일부 스킬만',
  inherited_note: '아직 이 프로젝트에 정한 것이 없어 기본값을 씁니다',
  add_project: '+ 폴더 추가', add_project_tip: '아무 폴더나 됩니다. git 저장소가 아니어도 됩니다',
  add_project_prompt: '추가할 폴더의 전체 경로:',
  add_project_failed: '폴더를 추가하지 못했습니다: ',
  no_project_yet: '아직 폴더가 없습니다',
  loaded: (n, tok) => `이 프로젝트는 스킬 <b>${n}개</b>를 로드합니다 (세션마다 약 <b>${tok.toLocaleString()}토큰</b>)`,
  loaded_tip: '스킬은 쓰든 안 쓰든 이름과 설명이 세션 시작 때 전부 올라갑니다. 명세는 그 양을 스킬 하나당 약 100토큰으로 적고 있고, 실제 값은 설명 길이에 따라 다릅니다.',
  spec_issue: '명세 위반',
  issue: {
    unreadable: () => 'SKILL.md를 읽지 못했습니다',
    no_frontmatter: () => 'YAML frontmatter가 없습니다',
    name_missing: () => 'name이 없습니다',
    name_format: i => `name "${i.name}" — 소문자·숫자·하이픈 하나씩만, 64자 이내`,
    name_mismatch: i => `name "${i.name}"이 폴더 이름 "${i.folder}"과 다릅니다`,
    desc_missing: () => 'description이 없습니다',
    desc_long: i => `description이 ${i.len}자입니다 (상한 1024)`,
  },
  scan_truncated: '프로젝트가 커서 탐색을 중간에 멈췄습니다. 더 아래에 있는 지침 파일은 빠졌을 수 있습니다.',
    no_subagents: '서브에이전트 없음',
    loading: '불러오는 중…', error: '오류: ',
    toggle_failed: '켜고 끄지 못했습니다: ', group_update_failed: '그룹을 바꾸지 못했습니다: ',
    plugin_on_tip: '이 프로젝트에서 켜져 있습니다. 누르면 꺼집니다 (다음 세션부터)',
    plugin_off_tip: '이 프로젝트에서 꺼져 있습니다. 누르면 켜집니다 (다음 세션부터)',
    skills_count: n => '스킬 ' + n + '개',
    group_tag: g => '그룹: ' + g, group_tag_tip: '그룹 탭에서 관리합니다',
    from: '출처: ',
    read_full_tip: '설명 전체 보기',
    no_skills_found: '스킬이 없습니다',
    updated: '갱신 ', every_n: n => `${n}초마다`, paused: '멈춤',
    usage: (mb, cpu) => `${mb}MB` + (cpu === null ? '' : ` · CPU ${cpu}%`),
    period_tip: '이 화면이 파일을 얼마나 자주 다시 읽을지',
    switching: '바꾸는 중…',
    update_available: (v, latest, repo) => `↑ v${latest} 나왔습니다 (지금은 v${v}) — <a href="https://github.com/${repo}/releases/latest" target="_blank" rel="noopener">릴리스 보기</a> 후 클론한 폴더에서 <code>git pull</code>, <code>./install.sh</code> 실행 (Homebrew: <code>brew upgrade agent-hud</code>)`,
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
// 플러그인 밖의 스킬은 펼친 채로 시작한다. 보통 몇 개뿐이고, 접어두면 있는 줄도 모른다.
if(!('__loose__' in skillsOpen)) skillsOpen['__loose__'] = true;
function stateUrl(){
  return '/api/state' + (selectedProject ? ('?project=' + encodeURIComponent(selectedProject)) : '');
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
    const r = await fetch('/api/toggle', {method:'POST', body: JSON.stringify({name, enable, project: currentProjectDir})});
    const d = await r.json();
    if(!d.ok) alert(t().toggle_failed + (d.error || t().error));
  } catch(e){ alert(t().toggle_failed + e); }
  polling = true;
  await tick();
}
async function editGroup(action, group, member, kind){
  polling = false;
  try{
    const r = await fetch('/api/group', {method:'POST', body: JSON.stringify({action, group, member, kind: kind || 'plugin'})});
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
async function assignSet(name, btn){
  polling = false; btn.classList.add('busy'); btn.textContent = t().switching;
  try{
    const r = await fetch('/api/activate', {method:'POST', body: JSON.stringify({group: name, project: currentProjectDir})});
    const d = await r.json();
    if(!d.ok) alert(t().assign_failed + (d.error || t().error));
  } catch(e){ alert(t().assign_failed + e); }
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
// 프로젝트 선택기. 두 탭이 같은 코드를 복사해 갖고 있었다.
// 목록이 비어도 보여준다 -- 폴더를 직접 더할 수 있어야 시작이 되기 때문이다.
function projectPicker(p){
  const box = document.createElement('div');
  box.style.cssText = 'display:flex;gap:8px;align-items:center;margin-bottom:10px';
  const sel = document.createElement('select');
  sel.style.cssText = 'background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:6px 8px;font-size:12px;flex:1;min-width:0';
  const list = p.known_projects || [];
  if(!list.length){
    const o = document.createElement('option'); o.textContent = t().no_project_yet; sel.appendChild(o);
    sel.disabled = true;
  }
  for(const pr of list){
    const o = document.createElement('option'); o.value = pr; o.textContent = pr;
    if(pr === p.project_dir) o.selected = true;
    sel.appendChild(o);
  }
  sel.onchange = () => { selectedProject = sel.value; localStorage.setItem('agent-hud-project', sel.value); rerender(); };
  const add = document.createElement('span'); add.className = 'card-action';
  add.textContent = t().add_project; add.title = t().add_project_tip;
  add.onclick = async () => {
    const path = (prompt(t().add_project_prompt) || '').trim();
    if(!path) return;
    polling = false;
    try{
      const r = await fetch('/api/register', {method:'POST', body: JSON.stringify({path})});
      const d = await r.json();
      if(!d.ok){ alert(t().add_project_failed + (d.error || t().error)); }
      else { selectedProject = path; localStorage.setItem('agent-hud-project', path); }
    } catch(e){ alert(t().add_project_failed + e); }
    polling = true;
    await tick();
  };
  box.appendChild(sel); box.appendChild(add);
  return box;
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
        const first = prompt(t().new_group_first_prompt + (p.all_plugins||[]).join('\n'));
        if(first) editGroup('add', name.trim(), first.trim(), 'plugin');
      };
      headerRow.appendChild(h); headerRow.appendChild(newBtn);
      c.appendChild(headerRow);
      const legend = document.createElement('div'); legend.className='note'; legend.style.marginBottom='14px';
      legend.textContent = t().groups_legend;
      c.appendChild(legend);
      for(const g of p.groups){
        const wrap = document.createElement('div'); wrap.className = 'section';
        const el = document.createElement('div'); el.className='row sec-head';

        const left = document.createElement('span'); left.className = 'sec-left';
        const gname = document.createElement('span'); gname.style.fontWeight='600';
        gname.textContent = g.name;
        left.appendChild(gname);
        const plugins = g.members.filter(m => m.kind === 'plugin');
        const skills = g.members.filter(m => m.kind === 'skill');
        const cnt = document.createElement('span'); cnt.className='tag';
        cnt.textContent = t().set_count(plugins.length, skills.length);
        left.appendChild(cnt);

        const right = document.createElement('span'); right.className = 'sec-right';
        const apply = document.createElement('span');
        apply.className = 'btn' + (g.assigned ? ' btn-on' : '');
        apply.textContent = g.assigned ? t().set_applied : t().set_apply;
        apply.title = t().set_apply_tip;
        apply.onclick = () => {
          if(g.assigned){
            if(confirm(t().unassign_confirm(g.name, p.project_dir))) assignSet('', apply);
          } else if(confirm(t().assign_confirm(g.name, p.project_dir,
              plugins.map(m=>m.name).join(', ') || '-', skills.length))){
            assignSet(g.name, apply);
          }
        };
        right.appendChild(apply);
        el.appendChild(left); el.appendChild(right);
        wrap.appendChild(el);

        for(const m of g.members){
          const mrow = document.createElement('div'); mrow.className='row sub';
          const mleft = document.createElement('span'); mleft.className = 'sec-left';
          const mdot = document.createElement('span'); mdot.className = 'dot ' + (m.on?'on':'off');
          mdot.style.cursor = 'default';
          mdot.title = m.kind === 'plugin' ? t().member_plugin_tip : t().member_skill_tip;
          mleft.appendChild(mdot);
          const mn = document.createElement('span'); mn.textContent = m.name;
          mleft.appendChild(mn);
          const kind = document.createElement('span'); kind.className = 'comp';
          kind.textContent = m.kind === 'plugin' ? t().kind_plugin : t().kind_skill;
          mleft.appendChild(kind);
          const rm = document.createElement('span'); rm.className='tag clickable danger'; rm.textContent=t().remove;
          rm.title = t().remove_tip(m.name, g.name);
          rm.onclick = () => { if(confirm(t().remove_confirm(m.name, g.name))) editGroup('remove', g.name, m.name, m.kind); };
          mrow.appendChild(mleft); mrow.appendChild(rm);
          wrap.appendChild(mrow);
        }

        const addRow = document.createElement('div'); addRow.className='row sub';
        const addSel = document.createElement('select');
        addSel.style.cssText='background:var(--bg);color:var(--dim);border:1px solid var(--border);border-radius:8px;padding:4px 8px;font-size:12px;max-width:100%';
        const ph = document.createElement('option'); ph.value=''; ph.textContent=t().add_member_ph;
        addSel.appendChild(ph);
        const mk = (label, items, kind) => {
          const grp = document.createElement('optgroup'); grp.label = label;
          for(const it of items){
            if(g.members.some(m => m.name === it && m.kind === kind)) continue;
            const o = document.createElement('option'); o.value = kind + ':' + it; o.textContent = it;
            grp.appendChild(o);
          }
          if(grp.children.length) addSel.appendChild(grp);
        };
        mk(t().kind_plugin, p.all_plugins||[], 'plugin');
        mk(t().kind_skill, p.all_skills||[], 'skill');
        addSel.onchange = () => {
          if(!addSel.value) return;
          const [kind, ...rest] = addSel.value.split(':');
          editGroup('add', g.name, rest.join(':'), kind);
        };
        addRow.appendChild(addSel);
        wrap.appendChild(addRow);
        c.appendChild(wrap);
      }

    } else if(p.files){
      c.appendChild(h);
      c.appendChild(projectPicker(p));
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
        note.style.marginTop = '14px';
        note.innerHTML = `<span>${t().no_subagents}</span>`;
        c.appendChild(note);
      }
      // 목록 아래 캡션. 위에 두면 목록보다 먼저 읽혀서 "그래서 뭘 하라는 건지"가 된다.
      const an = document.createElement('div'); an.className='note';
      an.style.cssText = 'margin-top:4px;font-size:11px;opacity:.75';
      an.textContent = t().agents_note;
      c.appendChild(an);
    } else {
      c.appendChild(h);
      c.appendChild(projectPicker(p));
      if(typeof p.loaded === 'number'){
        // 스킬은 이름과 설명이 세션 시작 때 전부 올라간다. 안 쓰는 것도 자리를 차지하므로,
        // 주장하지 말고 지금 이 프로젝트의 숫자를 그대로 보여준다.
        const l = document.createElement('div'); l.className = 'loadline';
        l.title = t().loaded_tip;
        l.innerHTML = t().loaded(p.loaded, p.loaded * 100);
        c.appendChild(l);
      }
      if(p.agents){
        const n = document.createElement('div'); n.className = 'note'; n.style.marginBottom = '12px';
        n.textContent = t().skills_note;
        c.appendChild(n);
      }
      if(p.has_local === false){
        const d = document.createElement('div'); d.className='note';
        d.style.cssText = 'margin:-4px 0 10px;font-size:11px;opacity:.8';
        d.textContent = t().inherited_note;
        c.appendChild(d);
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
        // 스킬 말고 또 뭐가 들었는지. 체크박스는 스킬만 옮기므로 이게 안 보이면
        // 사용자는 플러그인이 통째로 간다고 오해한다.
        for(const comp of (row.components||[])){
          const tag = document.createElement('span');
          tag.className = 'comp' + (comp.portable ? '' : ' stays');
          const label = t().comp[comp.name] || comp.name;
          tag.textContent = t().comp_count(label, comp.n || 1);
          tag.title = (comp.portable ? t().comp_portable_tip : t().comp_stays_tip)(label);
          badges.appendChild(tag);
        }
        const st = row.section_state || {};
        // 플러그인 밖 스킬은 출처도 대상도 제각각이라 한 줄로 요약할 수 없다.
        for(const a of (isPlugin ? (p.agents||[]) : [])){
          const tag = document.createElement('span');
          const v = st[a] || 'none';
          tag.className = 'agenttag ' + (v === 'all' ? 'yes' : v === 'some' ? 'partial' : 'no');
          tag.textContent = shortAgent(a);
          tag.title = v === 'some' ? t().partly : v === 'all' ? t().badge_on_tip(a) : t().badge_off_tip(a);
          badges.appendChild(tag);
        }
        meta.appendChild(badges);
        const secMiss = (p.agents||[]).filter(a => (st[a] || 'none') !== 'all');
        const ids = (row.skills||[]).filter(x => x.linkable).map(x => x.id);
        if(ids.length && isPlugin){
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

              const stext = document.createElement('div'); stext.className = 'skill-text';
              const sname = document.createElement('div'); sname.className = 'skill-name';
              sname.textContent = s.name;
              if((s.issues||[]).length){
                // 명세 위반이지 로드 실패가 아니다. 표현을 그렇게 유지할 것.
                const w = document.createElement('span'); w.className = 'warn';
                w.textContent = t().spec_issue;
                w.title = s.issues.map(i => (t().issue[i.code] || (x=>i.code))(i)).join('\n');
                sname.appendChild(w);
              }
              const full = s.desc||'';
              const sdesc = document.createElement('div'); sdesc.className = 'dim skill-desc';
              sdesc.textContent = full;
              stext.appendChild(sname); stext.appendChild(sdesc);

              // 섹션과 같으면 아무것도 안 그린다. 같은 사실을 줄마다 되풀이하지 않는다.
              const badges = document.createElement('span');
              const secUniform = isPlugin && (p.agents||[]).every(a => (row.section_state||{})[a] !== 'some');
              const sec = (p.agents||[]).filter(a => (row.section_state||{})[a] === 'all').join('|');
              if(!secUniform || (s.agents||[]).join('|') !== sec){
                for(const a of (p.agents||[])){
                  const tag = document.createElement('span');
                  const on = (s.agents||[]).includes(a);
                  tag.className = 'agenttag ' + (on ? 'yes' : 'no');
                  tag.textContent = shortAgent(a);
                  tag.title = on ? t().badge_on_tip(a) : t().badge_off_tip(a);
                  badges.appendChild(tag);
                }
              }
              srow.appendChild(stext); srow.appendChild(badges);
              if(s.linkable){
                // 섹션과 같은 말이면 글자를 반복하지 않는다. 뱃지와 같은 규칙.
                const miss = (s.missing||[]).map(shortAgent);
                const secAll = (p.agents||[]).filter(a => (row.section_state||{})[a] === 'all');
                const uniform = isPlugin && (p.agents||[]).every(a => (row.section_state||{})[a] !== 'some');
                const sameAsSection = uniform && (s.agents||[]).join('|') === secAll.join('|');
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
            project = payload.get("project", "") or PROJECT_DIR
            if project not in known_projects():
                return self._send_json({"ok": False, "error": "unknown project"}, 400)
            ok, err = set_plugins({payload.get("name", ""): bool(payload.get("enable"))}, project)
            self._send_json({"ok": ok, "error": err})
        elif self.path == "/api/group":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send_json({"ok": False, "error": "bad request"}, 400)
            ok, err = modify_group(payload.get("action", ""), payload.get("group", ""),
                                   payload.get("member", "") or payload.get("plugin", ""),
                                   payload.get("kind", "plugin"))
            self._send_json({"ok": ok, "error": err})
        elif self.path == "/api/activate":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send_json({"ok": False, "error": "bad request"}, 400)
            project = payload.get("project", "") or PROJECT_DIR
            if project not in known_projects():
                return self._send_json({"ok": False, "error": "unknown project"}, 400)
            ok, err = assign_set(payload.get("group", ""), project)
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


def cli_groups():
    """설정해둔 그룹과, 지금 폴더에 무엇이 적용돼 있는지."""
    sets = read_sets()
    if not sets:
        print("정의된 그룹이 없습니다. 대시보드에서 만들 수 있습니다.")
        return 0
    here = os.path.abspath(os.getcwd())
    assigned = read_json(SETS_FILE, {}).get(here, "")
    for name, entry in sets.items():
        mark = " ← 이 폴더에 적용됨" if name == assigned else ""
        print(f"{name}  플러그인 {len(entry['plugins'])} · 스킬 {len(entry['skills'])}{mark}")
    return 0


def cli_apply(group, project_dir):
    """그룹을 폴더에 적용한다. 서버가 떠 있지 않아도 된다 -- 같은 함수를 직접 부른다."""
    project_dir = os.path.abspath(project_dir)
    if not os.path.isdir(project_dir):
        print(f"폴더가 없습니다: {project_dir}", file=sys.stderr)
        return 1
    if group and group not in read_sets():
        print(f"그런 그룹이 없습니다: {group}", file=sys.stderr)
        print("agent-hud groups 로 목록을 볼 수 있습니다.", file=sys.stderr)
        return 1
    register_project(project_dir)      # 대시보드 목록에도 올려둔다
    ok, err = assign_set(group, project_dir)
    if not ok:
        print(f"적용하지 못했습니다: {err}", file=sys.stderr)
        return 1
    what = f'"{group}" 적용' if group else "적용 해제"
    print(f"{what} — {project_dir}")
    print("플러그인 변경은 다음 세션부터 반영됩니다.")
    return 0


USAGE = """agent-hud                      대시보드를 띄웁니다
agent-hud groups               그룹 목록
agent-hud apply <그룹> [폴더]   그룹을 폴더에 적용 (기본: 현재 폴더)
agent-hud apply --off [폴더]    적용 해제"""


def main():
    if os.environ.get("CLAUDE_HUD_DISABLE") == "1":
        return
    global PROJECT_DIR
    argv = sys.argv[1:]
    if argv and argv[0] in ("groups", "apply", "-h", "--help", "help"):
        if argv[0] in ("-h", "--help", "help"):
            print(USAGE)
            sys.exit(0)
        if argv[0] == "groups":
            sys.exit(cli_groups())
        rest = argv[1:]
        if not rest:
            print(USAGE, file=sys.stderr)
            sys.exit(1)
        group = "" if rest[0] == "--off" else rest[0]
        target = rest[1] if len(rest) > 1 else os.getcwd()
        sys.exit(cli_apply(group, target))
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
    cleanup_known_projects()
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
