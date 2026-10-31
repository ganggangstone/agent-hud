#!/usr/bin/env python3
"""Agent HUD: live status dashboard for a local Claude Code setup.

Extensibility: add a new panel by writing one function of shape
    def collect_x(ctx) -> dict   and appending it to PANELS.
Add a new plugin group by editing modes.json, or via the "+" button in the
dashboard UI itself — no code change needed either way.
"""
import json, os, re, shlex, urllib.request, http.server, socketserver, threading, webbrowser, sys, time, subprocess, shutil, resource, struct, zlib
from collections import deque
from contextlib import contextmanager
import fcntl

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
# 기본값은 스크립트 옆이다 -- 저장소에서 바로 실행하거나 install.sh로 복사해 쓰는 경우.
# AGENT_HUD_HOME으로 옮길 수 있다. 패키지 매니저로 설치하면 코드가 업그레이드마다 통째로
# 갈리는 곳에 놓이므로, 사용자 데이터를 거기 두면 그룹과 프로젝트 목록이 날아간다.
TOOL_DIR = os.environ.get("AGENT_HUD_HOME") or os.path.dirname(os.path.abspath(__file__))
os.makedirs(TOOL_DIR, exist_ok=True)
PROJECTS_FILE = os.path.join(TOOL_DIR, "projects.json")
MODES_FILE = os.path.join(TOOL_DIR, "modes.json")
PROJECT_DIR = os.getcwd()  # fallback: cwd of whichever invocation started this process

VERSION = "0.6.2"
# 주소는 늘 같아야 한다. "앱으로 설치"한 Dock 아이콘과 북마크가 이 주소에 묶이므로, 포트가 밀리면
# 그것들이 다른 프로그램을 열게 된다. 개발 도구가 흔히 쓰는 번호(3000, 8000, 8080 등)와 겹치지 않고,
# macOS가 임시로 나눠 주는 범위(49152~)보다 아래인 번호를 쓴다.
PORT = int(os.environ.get("AGENT_HUD_PORT") or 41717)
UPDATE_REPO = "ganggangstone/agent-hud"
UPDATE_CACHE_FILE = os.path.join(TOOL_DIR, ".update_check.json")
UPDATE_CHECK_INTERVAL_SEC = 24 * 60 * 60


# 세션 훅과 화면 폴링이 동시에 목록을 고친다. 잠그지 않으면 한쪽이 읽는 사이 다른 쪽이 쓰다 만 파일을
# 읽고, 못 읽은 것을 빈 목록으로 알고 그 위에 써서 목록이 통째로 사라진다.
_projects_lock = threading.Lock()


def write_json(path, data, **kw):
    """다 쓴 뒤에 바꿔 끼운다. 쓰는 도중에 읽는 쪽이 반쯤 쓴 파일을 보지 않는다."""
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, **kw)
    os.replace(tmp, path)


def remember_project(path):
    """이미 아는 프로젝트면 아무것도 하지 않는다. 발견할 때마다 시각을 갱신하면
    자동 발견된 폴더가 매번 목록 맨 위로 올라온다."""
    if path in ("/", HOME):
        return
    with _projects_lock:
        projects = read_json(PROJECTS_FILE, {})
        if path in projects:
            return
        projects[path] = time.time() - 86400        # 직접 연 프로젝트보다 뒤에 놓는다
        try:
            write_json(PROJECTS_FILE, projects)
        except Exception:
            pass


def register_project(path):
    """Record a project dir as 'seen' so the dashboard can offer it in the project dropdown."""
    if path in ("/", HOME):
        return  # server's own cwd under launchd, not a real project
    with _projects_lock:
        projects = read_json(PROJECTS_FILE, {})
        projects[path] = time.time()
        try:
            write_json(PROJECTS_FILE, projects)
        except Exception:
            pass
    if os.path.isdir(path):
        remove_stale_skill_denies(path)


def unregister_project(path):
    """목록에서만 뺀다. 폴더와 그 안의 설정은 건드리지 않는다."""
    with _projects_lock:
        projects = read_json(PROJECTS_FILE, {})
        if projects.pop(path, None) is None:
            return
        try:
            write_json(PROJECTS_FILE, projects)
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
    # 읽는 파일은 전부 JSON 객체다. [] 처럼 형식만 맞는 값을 그대로 넘기면 뒤따르는 .get()에서
    # 화면 전체가 실패하므로, 객체가 아니면 못 읽은 것과 똑같이 취급한다.
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return default if default is not None else {}


# 여기서는 새 버전이 있는지만 확인한다. 내려받는 건 사용자가 알림의 버튼을 눌렀을 때 brew가 하고
# (brew_update), git 설치본은 에이전트에게 맡길 문장을 복사해 준다. 근거는 docs/ADR.md 7번.
def _fetch_latest_release():
    req = urllib.request.Request(
        f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "agent-hud"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
    return (data.get("tag_name") or "").lstrip("v") or None


def _update_wait(now=None):
    """마지막 확인에서 하루가 지날 때까지 남은 초. 서버가 다시 떠도(로그인, launchd 재시작)
    하루에 한 번보다 자주 나가지 않게 한다. 시계가 뒤로 가도 하루보다 오래 기다리지는 않는다."""
    last = read_json(UPDATE_CACHE_FILE).get("checked_at") or 0
    left = last + UPDATE_CHECK_INTERVAL_SEC - (time.time() if now is None else now)
    return min(UPDATE_CHECK_INTERVAL_SEC, max(0, left))


def _update_check_loop():
    # 항상 백그라운드 스레드에서만 돈다 — /api/state 요청 경로는 절대 네트워크를 기다리지 않는다.
    while True:
        time.sleep(_update_wait())
        latest = read_json(UPDATE_CACHE_FILE).get("latest")
        try:
            latest = _fetch_latest_release() or latest
        except Exception:
            pass  # 오프라인이면 조용히 넘어간다 — 대시보드 본 기능과 무관
        # 실패해도 시각은 남긴다. 요청은 이미 나갔으므로 하루 한 번이라는 약속에 포함된다.
        try:
            write_json(UPDATE_CACHE_FILE, {"latest": latest, "checked_at": time.time()})
        except Exception:
            pass


def pick_folder():
    """브라우저는 고른 폴더의 실제 경로를 페이지에 알려주지 않는다. 서버가 이 맥에서 돌고 있으니
    Finder의 폴더 고르기 창을 서버가 띄운다. 창을 띄울 수 없으면 None(경로를 직접 입력받는다),
    취소하면 ""."""
    if sys.platform != "darwin":
        return None
    try:
        r = subprocess.run(["osascript", "-e", "activate", "-e", "POSIX path of (choose folder)"],
                           capture_output=True, text=True, timeout=600)
    except Exception:
        return None
    if r.returncode:
        return "" if "-128" in r.stderr else None       # -128: 사용자가 취소했다
    return r.stdout.strip().rstrip("/") or "/"


def brew_prefix(path=__file__):
    """Homebrew로 설치됐으면 brew가 있는 접두 경로(/opt/homebrew 등), 아니면 None.
    formula가 server.py를 <접두>/Cellar/agent-hud/<버전>/libexec/에 둔다."""
    marker = os.sep + os.path.join("Cellar", "agent-hud") + os.sep
    here = os.path.realpath(path)
    if marker not in here:
        return None
    prefix = here.split(marker)[0]
    return prefix if os.path.isfile(os.path.join(prefix, "bin", "brew")) else None


_update_lock = threading.Lock()


def brew_update(prefix, latest):
    """버튼 한 번으로 Homebrew 설치본을 올린다. (ok, 오류 문장)을 돌려준다.
    파일을 바꾸는 건 brew다 -- 서버는 명령을 부르고 끝나면 새 코드로 다시 뜰 뿐이다.
    git으로 설치한 쪽은 코드를 고쳐 쓰고 있을 수 있어 이 경로를 열지 않는다(ADR 7번)."""
    if not _update_lock.acquire(blocking=False):
        return False, "already updating"
    try:
        brew = os.path.join(prefix, "bin", "brew")
        # upgrade 전에 update를 따로 부른다. brew는 24시간 안에 한 번 받은 탭을 다시 받지
        # 않아서, 릴리스 직후에는 upgrade만으로는 새 버전을 못 볼 수 있다.
        for cmd in ([brew, "update"], [brew, "upgrade", "agent-hud"]):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if r.returncode != 0:
                tail = (r.stderr or r.stdout).strip().splitlines()
                return False, tail[-1] if tail else f"{cmd[1]} failed"
        r = subprocess.run([brew, "list", "--versions", "agent-hud"], capture_output=True, text=True, timeout=60)
        if all(newer(latest, v) for v in r.stdout.split()[1:]):
            return False, "Homebrew does not have the new version yet"
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        _update_lock.release()


def restart_into(prefix):
    """brew가 새 코드를 깔았으니 같은 프로세스를 새 코드로 바꾼다. launchd 서비스로 떠 있어도
    PID가 그대로라 서비스가 끊기지 않는다. 열려 있는 탭이 알아서 새로고침하므로 새 탭은 열지 않는다."""
    time.sleep(1)  # 응답이 브라우저에 닿을 시간
    exe = os.path.join(prefix, "bin", "agent-hud")
    # 토큰 세기 도구가 아직 없으면 여기서 같이 준비한다. 사용자가 누른 업데이트라 네트워크를
    # 이미 쓰는 중이고, 새 설치본의 명령을 부르므로 그쪽 파이썬·데이터 폴더를 그대로 따른다.
    # 실패해도 업데이트는 끝난 것이니 다시 뜨는 것은 막지 않는다.
    if not _tokenizer_python():
        try:
            subprocess.run([exe, "tokens", "setup"], capture_output=True, text=True,
                           timeout=SETUP_VENV_SECONDS + SETUP_PIP_SECONDS + 300)
        except Exception:
            pass
    os.environ["AGENT_HUD_NO_BROWSER"] = "1"
    os.execv(exe, [exe])


def start_in_background():
    """`agent-hud open`이 서버가 꺼져 있을 때 부른다. Homebrew 설치본이면 서비스를 켜서 로그인할
    때도 뜨게 하고, 아니면 이 파일을 셸과 떨어진 프로세스로 띄운다."""
    prefix = brew_prefix()
    if prefix:
        subprocess.run([os.path.join(prefix, "bin", "brew"), "services", "start", "agent-hud"],
                       capture_output=True, timeout=120)
        return
    subprocess.Popen([sys.executable, os.path.abspath(__file__)], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env=dict(os.environ, AGENT_HUD_NO_BROWSER="1"))


def newer(a, b):
    """a가 b보다 새 버전인가. 설치본이 저장해 둔 최신 버전보다 앞서 있으면(확인은 하루 한 번이다)
    알림을 띄우지 않아야 한다."""
    v = lambda s: tuple(int(x) for x in re.findall(r"\d+", s or ""))
    return v(a) > v(b)


def collect_update(ctx):
    cached = read_json(UPDATE_CACHE_FILE, {})
    latest = cached.get("latest")
    return {
        "panel": "update",
        "version": VERSION,
        "latest": latest,
        "has_update": newer(latest, VERSION),
        "repo": UPDATE_REPO,
        "brew": bool(brew_prefix()),
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
                     + [{"name": sk, "kind": "skill", "on": skill_is_shared(project_dir, sk, sources[sk])} for sk in skills],
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
META_READ_MAX = 1_000_000     # 닫는 ---가 안 나오는 파일에서 멈추는 상한


def _skill_meta(path, folder):
    """SKILL.md를 한 번 읽어 (표시 이름, 설명, 명세 위반 목록)."""
    name, desc, issues = folder, "", []
    lines, closed = [], False
    try:
        with open(path, encoding="utf-8") as f:
            first = f.readline(META_READ_MAX)
            if first.rstrip() != "---":
                return name, desc, [{"code": "no_frontmatter"}]
            size = len(first)
            # 경계는 줄 단위다(설명 안의 `---`는 경계가 아니다). 닫는 줄을 못 보면 상한까지만 읽고 멈춘다.
            while size < META_READ_MAX:
                line = f.readline(META_READ_MAX - size)
                if not line:
                    break
                size += len(line)
                if line.rstrip() == "---" and (line.endswith("\n") or size < META_READ_MAX):
                    closed = True
                    break
                lines.append(line.rstrip("\n"))
    except Exception:
        return name, desc, [{"code": "unreadable"}]
    if not closed:      # 닫히지 않았거나 상한에서 잘렸다: 설명이 어디까지인지 모른다
        return name, desc, [{"code": "frontmatter_unclosed"}]
    declared = None
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
    ("AGENTS.override.md", "Codex (replaces AGENTS.md)"),
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


# `@경로` 가져오기는 Claude Code만 따른다 (Codex·Antigravity는 글자로만 본다, ADR 참고).
# 그래서 이 이름의 파일에서만 해석한다. 다른 도구끼리 같은 내용을 쓰는 방법은 심볼릭 링크뿐이다.
_IMPORT_FILES = {"CLAUDE.md", "CLAUDE.local.md"}


# Claude Code v2.1.314에서 센티널 파일로 측정한 규칙: 문장 속 @도 읽고, 코드 블록·코드 스팬·따옴표는
# 건너뛰고, 공백은 역슬래시로 적고, 앞 글자가 붙은 me@x 는 아니고, 네 단계까지 따라간다.
_IMPORT_RE = re.compile(r"(?:^|(?<=\s))@((?:\\ |[^\s\\])+)")
_FENCE_RE = re.compile(r"\s{0,3}(`{3,}|~{3,})")
_CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)")  # 짝이 맞는 백틱만
MAX_IMPORT_HOPS = 4


def _import_targets(path):
    """path 에 적힌 @가져오기 -> [{path, ok}]. 줄 맨 앞인데 없는 파일은 깨진 연결로 남기고,
    문장 속인데 없는 파일은 그냥 글자로 본다(\"ask @someone\")."""
    targets, fence = [], None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _FENCE_RE.match(line)
                if fence:
                    if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line[m.end():].strip():
                        fence = None
                    continue
                if m:
                    fence = m.group(1)
                    continue
                for im in _IMPORT_RE.finditer(_CODE_SPAN_RE.sub(" ", line)):
                    raw = im.group(1)
                    if raw[0] in "\"'":
                        continue
                    t = os.path.expanduser(raw.replace("\\ ", " "))
                    if not os.path.isabs(t):
                        t = os.path.normpath(os.path.join(os.path.dirname(path), t))
                    ok = os.path.isfile(t)
                    if ok or im.start() == 0:
                        targets.append({"path": t, "ok": ok})
    except OSError:
        return []
    return targets


def _link_info(path, imported=False):
    """파일이 다른 파일과 어떻게 이어져 있는지. 심볼릭 링크 → 대상, @가져오기 → 대상 목록,
    둘 다 아니면 None(독립 파일). 어느 쪽이 원본인지는 판단하지 않는다.
    imported: Claude Code가 이미 가져온 파일이라 이름과 상관없이 @를 해석한다."""
    if os.path.islink(path):
        target = os.readlink(path)
        if not os.path.isabs(target):
            target = os.path.normpath(os.path.join(os.path.dirname(path), target))
        return {"kind": "symlink", "target": target, "ok": os.path.isfile(target)}
    if not os.path.isfile(path) or not (imported or os.path.basename(path) in _IMPORT_FILES):
        return None
    targets = _import_targets(path)
    return {"kind": "import", "targets": targets} if targets else None


def _with_link_targets(rows):
    """링크·@가 가리키는 파일 중 아직 행이 없는 것을 뒤에 행으로 더한다. 가져온 파일 안의 @도
    네 단계까지 따라간다. 어느 행을 거쳐 닿았는지는 via에 적는다. 없는 대상은 행으로 만들지 않는다
    (가리키는 쪽 뱃지가 이미 말한다)."""
    rows = list(rows)
    by_path = {r["path"]: r for r in rows}
    hops = {}
    queue = deque(rows)
    while queue:
        r = queue.popleft()
        link = r.get("link")
        if not link:
            continue
        is_import = link["kind"] == "import"
        hop = hops.get(r["path"], 0)
        if is_import and hop >= MAX_IMPORT_HOPS:
            continue
        read_by_claude = is_import or r["path"] in hops or os.path.basename(r["path"]) in _IMPORT_FILES
        for t in ([link["target"]] if not is_import else [x["path"] for x in link["targets"]]):
            if not os.path.isfile(t):
                continue
            row = by_path.get(t)
            if row is None:
                row = by_path[t] = _file_row(t, t, "")
                row["via"] = []
                rows.append(row)
                queue.append(row)
            if "via" in row:
                row["via"].append(r["name"])
            if read_by_claude:
                hops.setdefault(t, hop + 1 if is_import else hop)
                if not row.get("link"):
                    row["link"] = _link_info(t, imported=True)
                    if row["link"] and row not in queue:    # 이미 지나간 행이면 다시 본다
                        queue.append(row)
    return rows


MANAGED_SETTINGS = ("/Library/Application Support/ClaudeCode/managed-settings.json" if sys.platform == "darwin"
                    else "/etc/claude-code/managed-settings.json")


def claude_md_excludes(project_dir):
    """이 프로젝트에 적용되는 claudeMdExcludes -> 정규식 목록. 설정 계층의 배열은 합쳐진다(공식 문서)."""
    patterns = []
    for f in (MANAGED_SETTINGS, os.path.join(CLAUDE_DIR, "settings.json"),
              os.path.join(project_dir, ".claude", "settings.json"),
              os.path.join(project_dir, LOCAL_SETTINGS)):
        v = read_json(f).get("claudeMdExcludes")
        if isinstance(v, list):
            patterns += [_glob_regex(p) for p in v if isinstance(p, str)]
    return patterns


def _glob_regex(pattern):
    """절대 경로에 맞추는 glob. ** 는 폴더 경계를 넘고 * 와 ? 와 [abc] 는 넘지 않는다."""
    rx = {"**/": "(?:.*/)?", "**": ".*", "*": "[^/]*", "?": "[^/]"}
    def part_rx(part):
        if part in rx:
            return rx[part]
        if len(part) > 2 and part[0] == "[" and part[-1] == "]":
            body = part[1:-1]
            return "[" + ("^/" + re.escape(body[1:]) if body[0] == "!" else re.escape(body)) + "]"
        return re.escape(part)
    return re.compile("".join(part_rx(p) for p in re.split(r"(\*\*/|\*\*|\*|\?|\[[^\]/]+\])", pattern)))


def _claude_excluded(path, patterns):
    """링크는 링크 경로와 대상 경로 어느 쪽으로도 제외된다(공식 문서)."""
    return any(p.fullmatch(q) for p in patterns for q in (path, os.path.realpath(path)))


def _imports_of(path, depth=0, excludes=(), seen=None):
    """path 와 그 @가져오기 대상(있는 것만, 네 단계까지). 링크는 대상 파일로 풀고 상대 경로도
    대상 파일 기준이다(측정). 제외된 파일은 그 @대상까지 읽히지 않는다."""
    real = os.path.realpath(path)
    seen = set() if seen is None else seen
    if real in seen or not os.path.isfile(real) or _claude_excluded(path, excludes):
        return []
    seen.add(real)
    out = [real]
    if depth < MAX_IMPORT_HOPS:
        for t in _import_targets(real):
            if t["ok"]:
                out += _imports_of(t["path"], depth + 1, excludes, seen)
    return out


def _dirs_from_root(project_dir):
    """파일시스템 루트부터 project_dir 까지."""
    out, cur = [], os.path.abspath(project_dir)
    while True:
        out.append(cur)
        parent = os.path.dirname(cur)
        if parent == cur:
            return out[::-1]
        cur = parent


def _frontmatter_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            m = re.match(r"---\s*\n(.*?)\n---", f.read(8192), re.S)
    except OSError:
        return ""
    return m.group(1) if m else ""


def _claude_rules(folder):
    """시작 때 읽는 규칙: 하위 폴더까지의 .md 중 paths 가 없는 것(측정)."""
    out, visited = [], set()
    for cur, subs, files in os.walk(folder, followlinks=True):
        real = os.path.realpath(cur)
        if real in visited:     # 순환 링크
            subs[:] = []
            continue
        visited.add(real)
        subs.sort()
        out += [os.path.join(cur, f) for f in sorted(files)
                if f.endswith(".md") and not re.search(r"^paths\s*:", _frontmatter_text(os.path.join(cur, f)), re.M)]
    return out


def _claude_instructions(project_dir):
    """전역, 그리고 파일시스템 루트부터 프로젝트까지 폴더마다(측정, v2.1.314). 프로젝트 쪽 CLAUDE 파일이
    하나도 없으면 AGENTS.md를 대신 읽는다. 전역 CLAUDE.md와 규칙은 이 판정에 들어가지 않는다."""
    dirs = _dirs_from_root(project_dir)
    names = (("CLAUDE.md",), (".claude", "CLAUDE.md"), ("CLAUDE.local.md",))
    has_claude = any(os.path.isfile(os.path.join(d, *n)) for d in dirs if d != HOME for n in names)
    out = [os.path.join(CLAUDE_DIR, "CLAUDE.md")] + _claude_rules(os.path.join(CLAUDE_DIR, "rules"))
    for d in dirs:
        out += [os.path.join(d, "CLAUDE.md"), os.path.join(d, ".claude", "CLAUDE.md")]
        if not has_claude:
            out += [os.path.join(d, "AGENTS.md"), os.path.join(d, ".claude", "AGENTS.md")]
        out += _claude_rules(os.path.join(d, ".claude", "rules")) + [os.path.join(d, "CLAUDE.local.md")]
    return out


MAX_AGY_LINK_DEPTH = 16     # 문서에 한도가 없다. 사슬이 길어도 집계가 죽지 않게 하는 안전장치다.


def _agy_expand(path, seen, depth=0):
    """@[이름](경로)는 본문에 넣는다. @이름 은 참조일 뿐이다(측정, 공식 문서)."""
    real = os.path.realpath(path)
    if real in seen or depth > MAX_AGY_LINK_DEPTH or not os.path.isfile(real):
        return []
    seen.add(real)
    out = [real]
    try:
        with open(real, encoding="utf-8", errors="replace") as f:
            for rel in re.findall(r"@\[[^\]]*\]\(([^)\s]+)\)", f.read(INSTRUCTION_READ_MAX)):
                t = os.path.expanduser(rel)
                out += _agy_expand(t if os.path.isabs(t) else os.path.join(os.path.dirname(real), t), seen, depth + 1)
    except OSError:
        pass
    return out


def _antigravity_instructions(project_dir):
    """시작 폴더의 지침 4종과 trigger: always_on 규칙(agy 측정), 전역 지침과 규칙(공식 문서)."""
    gem = os.path.join(HOME, ".gemini")
    P = lambda *a: os.path.join(project_dir, *a)
    files = [os.path.join(gem, "GEMINI.md"), os.path.join(gem, "AGENTS.md"),
             os.path.join(gem, "config", "GEMINI.md"), os.path.join(gem, "config", "AGENTS.md")]
    rule_dirs = [os.path.join(gem, "config", "rules")]
    files_after = [P("AGENTS.md"), P("GEMINI.md"), P(".agents", "AGENTS.md"), P(".agents", "GEMINI.md")]
    rule_dirs_after = [P(".agents", "rules"), P(".agent", "rules")]
    def always_on(folder):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            return []
        return [os.path.join(folder, n) for n in names if n.endswith(".md")
                and re.search(r"^trigger\s*:\s*always_on\s*$", _frontmatter_text(os.path.join(folder, n)), re.M)]
    out, seen = [], set()
    for f in files + [r for d in rule_dirs for r in always_on(d)] + files_after + [r for d in rule_dirs_after for r in always_on(d)]:
        out += _agy_expand(f, seen)
    return out


def _first_nonempty(*paths):
    for p in paths:
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            return [p]
    return []


def _codex_instructions(project_dir):
    """전역 하나, 그리고 Git 루트부터 프로젝트 폴더까지 폴더마다 하나. 빈 파일은 건너뛴다.
    루트를 못 찾으면 프로젝트 폴더만 본다(Codex 공식 문서)."""
    home = os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")
    out = _first_nonempty(os.path.join(home, "AGENTS.override.md"), os.path.join(home, "AGENTS.md"))
    dirs = _dirs_from_root(project_dir)
    roots = [i for i, d in enumerate(dirs) if os.path.exists(os.path.join(d, ".git"))]
    for d in dirs[roots[-1]:] if roots else [os.path.abspath(project_dir)]:
        out += _first_nonempty(os.path.join(d, "AGENTS.override.md"), os.path.join(d, "AGENTS.md"))
    return out


# 에이전트마다 세션을 시작할 때 늘 읽는 지침 파일. 하위 폴더의 파일은 그 폴더를 건드릴 때만
# 읽히므로 넣지 않는다. 출처: INSTRUCTION_SOURCES 의 도구 표와 각 도구 문서(ADR 11).
def session_instructions(project_dir):
    """-> {에이전트: [파일 경로]} (실재하는 것만, 링크는 대상으로, 중복 없이)"""
    P = lambda *a: os.path.join(project_dir, *a)
    plan = {
        "Claude Code": _claude_instructions(project_dir),
        "Codex": _codex_instructions(project_dir),
        "Gemini CLI": [os.path.join(HOME, ".gemini", "GEMINI.md"), P("GEMINI.md")],
        "Cursor": [P("AGENTS.md")],
        "Copilot": [P(".github", "copilot-instructions.md"), P("AGENTS.md")],
        "Antigravity": _antigravity_instructions(project_dir),
    }
    excludes = claude_md_excludes(project_dir)
    out = {}
    for agent, paths in plan.items():
        seen = []
        for p in paths:
            for f in (_imports_of(p, excludes=excludes) if agent == "Claude Code" else ([os.path.realpath(p)] if os.path.isfile(p) else [])):
                if f not in seen:
                    seen.append(f)
        out[agent] = seen
    return out


INSTRUCTION_READ_MAX = 400_000


def session_load(project_dir, tk):
    """머리글용: 에이전트마다 세션 시작 때 읽히는 지침 수·스킬 수·토큰 합(지침 본문 + 스킬 이름·설명).
    어느 한쪽이라도 못 셌으면 tokens 는 None. 스킬 쪽 수는 _attach_tokens 가 센 tk 를 그대로 쓴다."""
    files = session_instructions(project_dir)
    texts = {}
    for paths in files.values():
        for f in paths:
            if f not in texts:
                try:
                    with open(f, encoding="utf-8", errors="replace") as fh:
                        texts[f] = fh.read(INSTRUCTION_READ_MAX)
                except OSError:
                    texts[f] = None
    state, counts = count_tokens([t for t in texts.values() if t is not None]) if any(v is not None for v in texts.values()) else ("ok", {})
    out = {}
    for agent in SKILL_AGENTS:
        sk = (tk.get("agents") or {}).get(agent) or {"skills": 0, "measured": 0, "tokens": 0}
        instr = [texts[f] for f in files[agent]]
        ok = tk.get("state") == "ok" and state == "ok" and sk["measured"] == sk["skills"] and all(t is not None and t in counts for t in instr)
        out[agent] = {"instructions": len(instr), "skills": sk["skills"],
                      "tokens": (sk["tokens"] or 0) + sum(counts[t] for t in instr) if ok else None}
    return out


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
        "link": _link_info(path),
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
    (".gemini/antigravity-cli/skills", ["Antigravity"]),  # agy CLI 전역(Antigravity 공식 문서)
]


def _same_bytes(a, b):
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def _scan_skill_root(root, label, agents, found):
    """링크거나 내용이 똑같은 스킬만 한 행으로 합친다. 내용이 다르면 행을 나누고, 에이전트는 먼저 찾은
    쪽에 둔다. Claude Code만 전역이 프로젝트를 이긴다(공식 문서)."""
    if not os.path.isdir(root):
        return
    for name in sorted(os.listdir(root)):
        md = os.path.join(root, name, "SKILL.md")
        if not os.path.isfile(md):
            continue
        real = os.path.realpath(md)
        # 3초마다 도는 코드라 이름이 겹칠 때만 찾고 읽는다
        same_name = [r for r in found.values() if r["name"] == name] if name in found else []
        row = next((r for r in same_name if r["real"] == real or _same_bytes(r["path"], md)), None)
        if row is None:
            row = found[f"{name}@{label}" if same_name else name] = {
                "name": name, "agents": [], "roots": [], "path": md, "real": real}
        row["roots"].append(label)
        others = [r for r in same_name if r is not row]
        for a in agents:
            taken = [r for r in others if a in r["agents"]]
            if a == "Claude Code" and taken and label.startswith("~/"):
                for r in taken:
                    r["agents"].remove(a)
                taken = []
            if not taken and a not in row["agents"]:
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


def project_skills():
    """{스킬 이름: (원본 폴더, 프로젝트)}. 대시보드에 등록된 프로젝트 안에 실제 폴더로 놓인 스킬.
    한 프로젝트에서만 쓰던 스킬도 그룹에 넣어 다른 프로젝트에 걸 수 있게 한다. 링크는 원본으로
    받지 않는다 -- 다른 곳을 가리키는 링크를 원본으로 삼으면 링크를 가리키는 링크가 생긴다."""
    out = {}
    for proj in known_projects():
        for rel, _agents in SKILL_ROOTS_PROJECT:
            root = os.path.join(proj, rel.replace("/", os.sep))
            if not os.path.isdir(root):
                continue
            for name in sorted(os.listdir(root)):
                d = os.path.join(root, name)
                if not os.path.islink(d) and os.path.isfile(os.path.join(d, "SKILL.md")):
                    out.setdefault(name, (d, proj))
    return out


def skill_sources(project_dir):
    """{스킬 이름: 원본 폴더}. 플러그인, 사용자 스킬 폴더, 등록된 프로젝트의 실제 스킬 폴더 순으로
    찾고, 이름이 겹치면 앞의 것을 쓴다."""
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
    for name, (d, _proj) in project_skills().items():
        out.setdefault(name, d)
    return out


def skill_is_shared(project_dir, name, src=None):
    """이 프로젝트의 모든 스킬 폴더에서 그 스킬이 보이나. 링크가 걸려 있거나, 그 자리가 원본
    자체면 된다(원본이 이 프로젝트 안에 있는 경우)."""
    src = src or skill_sources(project_dir).get(name)
    if not _valid_skill_name(name):
        return False
    return bool(src) and all(_skill_path_state(project_dir, d, name, src) in ("linked", "original")
                            for d in GROUP_LINK_DIRS)


def link_skill(name, on, project_dir):
    """스킬 하나를 이 프로젝트의 모든 에이전트에게 열거나 닫는다.
    원본이 어디에 있든(플러그인·~/.claude·~/.agents) 비어 있는 폴더만 채운다 --
    그래서 방향(claude->agents, agents->claude)을 따질 필요가 없다."""
    if not project_dir or not os.path.isdir(project_dir):
        return False, "project not found"
    if not _valid_skill_name(name):
        return False, "invalid skill name"
    src = skill_sources(project_dir).get(name)
    if not src:
        return False, "unknown skill"
    try:
        for rel in GROUP_LINK_DIRS:
            dst = _link_path(project_dir, rel, name)
            state = _skill_path_state(project_dir, rel, name, src)
            if state == "blocked":
                return False, "skill directory is linked or inaccessible"
            if on:
                if state in ("linked", "original", "occupied"):
                    continue  # 진짜 폴더는 사용자 것이다. 건드리지 않는다.
                if state != "missing":
                    return False, "existing link has a different or unavailable source"
                result = _create_skill_link(project_dir, rel, name, src)
                if result not in ("created", "linked", "original"):
                    return False, "skill link could not be created: " + result
            elif os.path.islink(dst):
                if local_path(dst) != local_path(src):
                    return False, "existing link has a different source"
                os.unlink(dst)  # 링크만 지운다
    except Exception as e:
        return False, str(e)
    return True, ""


# Local HUD data, never written into a checkout or an agent's settings.
WORKTREE_FILE = os.path.join(TOOL_DIR, "worktree-skills.json")
_worktree_lock = threading.RLock()
WORKTREE_POLL_SECONDS = 15


@contextmanager
def _worktree_transaction():
    # The setup CLI and server are separate processes; a thread lock alone can
    # lose an exclusion or a newly saved default during automatic application.
    with _worktree_lock:
        with open(WORKTREE_FILE + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def local_path(path):
    """Resolve local aliases without traversing /Volumes, including symlink aliases.

    Conservatively leave every /Volumes path unchecked: Git's list can mention an
    unavailable network checkout and inspecting it can mount or scan that share.
    """
    if not isinstance(path, str) or not path or "\0" in path:
        return None
    path = os.path.abspath(path)
    for _ in range(40):
        parts = path.split(os.sep)
        cur = os.sep
        for i, part in enumerate(parts[1:], 1):
            cur = os.path.join(cur, part)
            if cur == "/Volumes" or cur.startswith("/Volumes/"):
                return None
            if os.path.islink(cur):
                target = os.readlink(cur)
                if not os.path.isabs(target):
                    target = os.path.join(os.path.dirname(cur), target)
                path = os.path.abspath(os.path.join(target, *parts[i + 1:]))
                break
        else:
            return path
    return None


def _git_read(path, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        p = subprocess.run(["git", "-C", path, *args], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3)
        return os.fsdecode(p.stdout) if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_repository(path):
    path = local_path(path)
    if not path or not os.path.isdir(path):
        return None
    top = _git_read(path, "rev-parse", "--show-toplevel")
    common = _git_read(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if top is None or common is None:
        return None
    top, common = local_path(top.removesuffix("\n")), local_path(common.removesuffix("\n"))
    return {"root": top, "common_dir": common} if top and common else None


def git_worktrees(repo):
    raw = _git_read(repo["root"], "worktree", "list", "--porcelain", "-z")
    if raw is None:
        return None  # distinguish an unavailable Git query from an empty list
    rows, row = [], {}
    for field in raw.split("\0"):
        if not field:
            if row:
                path = local_path(row["path"])
                actual = git_repository(path) if path else None
                row["available"] = bool(actual and actual["root"] == path and
                                        actual["common_dir"] == repo["common_dir"] and not row.get("prunable"))
                row["path"] = path or row["path"]
                rows.append(row)
                row = {}
        elif field.startswith("worktree "):
            row = {"path": field[9:], "branch": "", "detached": False}
        elif field.startswith("branch "):
            row["branch"] = field[7:].removeprefix("refs/heads/")
        elif field == "detached":
            row["detached"] = True
        elif field.startswith("prunable") or field == "bare":
            row["prunable"] = True
    return rows


def _valid_skill_name(name):
    return isinstance(name, str) and bool(name) and name not in (".", "..") and not any(
        c in name for c in ("/", "\\", "\0"))


def _skill_file_readable(source):
    if not source:
        return False
    md = local_path(os.path.join(source, "SKILL.md"))
    if not md or not os.path.isfile(md):
        return False
    try:
        with open(md, "rb") as file:
            file.read(1)
        return True
    except OSError:
        return False


def _skill_path_state(project, rel, name, source):
    # A linked parent directory must never become a write-through to another checkout.
    cur = project
    for part in rel.split("/"):
        cur = os.path.join(cur, part)
        if os.path.islink(cur) or (os.path.lexists(cur) and not os.path.isdir(cur)):
            return "blocked"
    dst = os.path.join(cur, name)
    real_src = local_path(source)
    if not _skill_file_readable(real_src):
        return "source_missing"
    if os.path.islink(dst):
        real = local_path(dst)
        if real is None:
            return "blocked"
        if not _skill_file_readable(real):
            return "broken"
        return "linked" if real == real_src else "conflict"
    if os.path.lexists(dst):
        return "original" if local_path(dst) == real_src else "occupied"
    return "missing"


def _validated_worktree_config(project, config, trusted=False):
    if not isinstance(config, dict):
        raise ValueError("invalid skill configuration")
    dirs, skills = config.get("dirs"), config.get("skills")
    if not isinstance(dirs, list) or not dirs or any(d not in GROUP_LINK_DIRS for d in dirs):
        raise ValueError("choose supported skill directories")
    if not isinstance(skills, list) or not skills:
        raise ValueError("choose at least one skill")
    sources = skill_sources(project) if not trusted else {}
    out, seen = [], set()
    for item in skills:
        if not isinstance(item, dict) or not _valid_skill_name(item.get("name")):
            raise ValueError("invalid skill name")
        name, source = item["name"], local_path(item.get("source"))
        if name in seen:
            raise ValueError("duplicate skill name")
        seen.add(name)
        if not _skill_file_readable(source):
            raise ValueError("skill source is unavailable: " + name)
        if not trusted and source != local_path(sources.get(name)):
            # Preserve the actual source of a shared project skill even when a
            # same-named plugin or user skill wins the general source index.
            existing = [local_path(_link_path(project, d, name)) for d in GROUP_LINK_DIRS]
            if source not in existing:
                raise ValueError("unknown skill source: " + name)
        out.append({"name": name, "source": source})
    return {"skills": out, "dirs": list(dict.fromkeys(dirs))}


def _worktree_plan(project, targets, config, trusted=False):
    project = local_path(project)
    repo = git_repository(project)
    if not repo or project != repo["root"]:
        raise ValueError("select a repository checkout root")
    config = _validated_worktree_config(project, config, trusted)
    worktrees = git_worktrees(repo)
    if worktrees is None:
        raise ValueError("could not read worktree list")
    available = {r["path"] for r in worktrees if r["available"]}
    if not isinstance(targets, list) or not targets:
        raise ValueError("choose a worktree")
    targets = [local_path(t) for t in targets]
    if any(t not in available for t in targets):
        raise ValueError("worktree is unavailable or belongs to a different repository")
    rows = [{"project": target, "dir": rel, "name": sk["name"], "source": sk["source"],
             "state": _skill_path_state(target, rel, sk["name"], sk["source"])}
            for target in dict.fromkeys(targets) for rel in config["dirs"] for sk in config["skills"]]
    return repo, config, rows


def preview_worktree_skills(project, targets, config):
    try:
        _, _, rows = _worktree_plan(project, targets, config)
        return {"ok": True, "rows": rows}
    except (ValueError, OSError) as e:
        return {"ok": False, "error": str(e), "rows": []}


def _fill_skill_link(row, repo):
    """Create one absent entry through directory FDs; never unlink an existing entry."""
    target = row["project"]
    actual = git_repository(target)
    if not actual or actual != {"root": target, "common_dir": repo["common_dir"]}:
        return "unavailable"
    return _create_skill_link(target, row["dir"], row["name"], row["source"])


def _create_skill_link(target, rel, name, source):
    target = local_path(target)
    if not target or not os.path.isdir(target):
        return "unavailable"
    state = _skill_path_state(target, rel, name, source)
    if state != "missing":
        return state
    fds = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(target, flags); fds.append(fd)
        for part in rel.split("/"):
            try:
                os.mkdir(part, dir_fd=fd)
            except FileExistsError:
                pass
            fd = os.open(part, flags, dir_fd=fd); fds.append(fd)
        # Check that the open root is still the visible checkout before writing.
        opened, visible = os.fstat(fds[0]), os.stat(target, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino):
            return "unavailable"
        if not _skill_file_readable(source):
            return "source_missing"
        os.symlink(source, name, dir_fd=fd)
        return "created"
    except FileExistsError:
        return _skill_path_state(target, rel, name, source)
    except OSError:
        return "blocked"
    finally:
        for fd in reversed(fds):
            os.close(fd)


def _apply_worktree_skills(project, targets, config, data, trusted=False):
    try:
        repo, _, rows = _worktree_plan(project, targets, config, trusted)
        for row in rows:
            row["state"] = _fill_skill_link(row, repo)
            if row["state"] == "created":
                dst = _link_path(row["project"], row["dir"], row["name"])
                data.setdefault("links", {})[dst] = row["source"]
        good = {"created", "linked", "original"}
        return {"ok": all(r["state"] in good for r in rows), "rows": rows}
    except (ValueError, OSError) as e:
        return {"ok": False, "error": str(e), "rows": []}


def apply_worktree_skills(project, targets, config):
    with _worktree_transaction():
        data = read_json(WORKTREE_FILE)
        result = _apply_worktree_skills(project, targets, config, data)
        try:
            write_json(WORKTREE_FILE, data, ensure_ascii=False, indent=2)
        except OSError as e:
            result.update(ok=False, error=str(e))
        return result


def set_worktree_policy(project, config, enabled):
    with _worktree_transaction():
        try:
            repo = git_repository(project)
            if not repo or local_path(project) != repo["root"]:
                raise ValueError("select a repository checkout root")
            data = read_json(WORKTREE_FILE)
            old = data.setdefault("repos", {}).get(repo["common_dir"], {})
            if enabled:
                config = _validated_worktree_config(project, config)
                rows = git_worktrees(repo)
                if rows is None:
                    raise ValueError("could not read worktree list")
                # Enabling or changing a default never changes existing worktrees.
                old.update(config=config, project=repo["root"], seen=[r["path"] for r in rows], targets=[])
            old["enabled"] = bool(enabled)
            data["repos"][repo["common_dir"]] = old
            write_json(WORKTREE_FILE, data, ensure_ascii=False, indent=2)
            return {"ok": True}
        except (ValueError, OSError) as e:
            return {"ok": False, "error": str(e)}


def set_worktree_override(project, target, mode, config=None):
    with _worktree_transaction():
        try:
            repo = git_repository(project)
            target = local_path(target)
            if not repo or local_path(project) != repo["root"]:
                raise ValueError("select a repository checkout root")
            rows = git_worktrees(repo)
            if rows is None or target not in {r["path"] for r in rows if r["available"]}:
                raise ValueError("worktree is unavailable")
            if mode not in ("inherit", "exclude", "custom"):
                raise ValueError("unknown worktree mode")
            entry = {"mode": mode}
            if mode == "custom":
                entry["config"] = _validated_worktree_config(project, config)
            data = read_json(WORKTREE_FILE)
            policy = data.setdefault("repos", {}).setdefault(repo["common_dir"], {})
            policy.setdefault("overrides", {})[target] = entry
            write_json(WORKTREE_FILE, data, ensure_ascii=False, indent=2)
            return {"ok": True}
        except (ValueError, OSError) as e:
            return {"ok": False, "error": str(e)}


def auto_apply_worktrees_once():
    with _worktree_transaction():
        data = read_json(WORKTREE_FILE)
        before = json.dumps(data, sort_keys=True)
        for common, policy in data.get("repos", {}).items():
            if not policy.get("enabled"):
                continue
            repo = git_repository(policy.get("project"))
            if not repo or repo["common_dir"] != common:
                continue
            rows = git_worktrees(repo)
            if rows is None:
                continue
            seen = set(policy.get("seen", []))
            targets = set(policy.get("targets", []))
            for row in rows:
                path = row["path"]
                if not row["available"]:
                    continue
                if path not in seen:
                    targets.add(path); seen.add(path)
                if path not in targets:
                    continue
                override = policy.get("overrides", {}).get(path, {})
                if override.get("mode") == "exclude":
                    continue
                config = override.get("config", policy.get("config"))
                result = _apply_worktree_skills(repo["root"], [path], config, data, trusted=True)
                results = policy.setdefault("results", {})
                previous = results.get(path, {})
                # Keep the last application time stable when a poll changes nothing.
                states = [{**r, "state": "linked" if r["state"] == "created" else r["state"]}
                          for r in result["rows"]]
                summary = {"ok": result["ok"], "error": result.get("error", ""), "rows": states}
                if any(previous.get(k) != v for k, v in summary.items()):
                    results[path] = {**summary, "at": time.time()}
            policy.update(seen=sorted(seen), targets=sorted(targets))
        if json.dumps(data, sort_keys=True) != before:
            write_json(WORKTREE_FILE, data, ensure_ascii=False, indent=2)


def _worktree_apply_loop():
    while True:
        try:
            auto_apply_worktrees_once()
        except Exception as e:
            print(f"agent-hud: worktree skill application failed: {e}", file=sys.stderr)
        time.sleep(WORKTREE_POLL_SECONDS)


def collect_worktrees(project):
    repo = git_repository(project)
    if not repo:
        return None
    data = read_json(WORKTREE_FILE)
    policy = data.get("repos", {}).get(repo["common_dir"], {})
    candidates = dict(skill_sources(project))
    # Actual project entries take priority here: the selected source is pinned,
    # not replaced later by a same-named skill from another installation.
    for rel in GROUP_LINK_DIRS:
        root = os.path.join(project, rel)
        if os.path.islink(root) or not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            src = local_path(os.path.join(root, name))
            if _skill_file_readable(src):
                candidates[name] = src
    skills = [{"name": n, "source": s, "selected": any(
        _skill_path_state(project, d, n, s) in ("linked", "original") for d in GROUP_LINK_DIRS)}
        for n, s in sorted(candidates.items()) if _valid_skill_name(n) and local_path(s)]
    rows = git_worktrees(repo)
    if rows is not None:
        # Previously known but now removed/pruned checkouts remain visible and
        # disabled. Listing history never probes or recreates these paths.
        current = {r["path"] for r in rows}
        historical = set(policy.get("seen", [])) | set(policy.get("overrides", {}))
        for path in sorted(historical - current):
            rows.append({"path": path, "branch": "", "detached": False, "available": False})
        for row in rows:
            override = policy.get("overrides", {}).get(row["path"], {})
            row["mode"] = override.get("mode", "inherit")
            config = override.get("config", policy.get("config"))
            row["config"] = config
            row["result"] = policy.get("results", {}).get(row["path"])
            config = config or {"skills": [sk for sk in skills if sk.get("selected")], "dirs": GROUP_LINK_DIRS}
            row["skills"] = [{"name": sk["name"], "dir": d,
                              "state": _skill_path_state(row["path"], d, sk["name"], sk["source"])}
                             for d in config["dirs"] for sk in config["skills"]] if config and row["available"] else []
    return {"common_dir": repo["common_dir"], "rows": rows or [], "query_failed": rows is None,
            "can_apply": local_path(project) == repo["root"], "enabled": bool(policy.get("enabled")),
            "config": policy.get("config"), "skills": skills, "poll_seconds": WORKTREE_POLL_SECONDS}


# 스킬 이름+설명의 참고용 토큰 수. 서버는 표준 라이브러리만 쓰고, 세는 일은 setup이 만든
# 별도 venv의 tiktoken에 맡긴다(`agent-hud tokens setup`). 설치하지 않았으면 숫자를 지어내지 않고
# "측정 안 함"으로 보여준다. 세는 대상은 SKILL.md 앞머리의 name + 줄바꿈 + description 뿐이고
# (본문 제외) 어떤 에이전트의 실제 로드량·청구액도 아니다.
TOKEN_ENCODING = "o200k_base"
TOKENIZER_REQUIREMENT = "tiktoken>=0.8,<1"     # 버전 범위는 여기 한 곳에만 둔다
TOKENIZER_VENV = os.path.join(TOOL_DIR, "tokenizer-venv")
TOKENIZER_CACHE = os.path.join(TOOL_DIR, "tokenizer-cache")
TOKEN_CACHE_MAX = 4096
TOKEN_FAIL_SECONDS = 15
TOKEN_INCOMPLETE = ("unreadable", "no_frontmatter", "frontmatter_unclosed", "name_missing", "desc_missing")

# venv의 파이썬에서 도는 고정 코드. stdin의 JSON 문자열 목록을 읽어 토큰 수 목록을 stdout에 낸다.
# count 모드는 소켓 연결을 막아 어휘 파일이 없을 때 몰래 내려받지 않고 "cache"로 실패한다.
# 특수 토큰처럼 생긴 글자(<|endoftext|> 등)도 보통 글자로 센다.
_TOKEN_SNIPPET = r"""
import json, os, sys
mode, cache, name = sys.argv[1:4]
os.environ["TIKTOKEN_CACHE_DIR"] = cache
def fail(code):
    print(json.dumps({"error": code})); sys.exit(3)
try:
    import tiktoken
except Exception:
    fail("import")
if mode == "count":
    import socket
    def deny(*a, **k): raise OSError("offline")
    socket.socket.connect = deny
    socket.getaddrinfo = deny
try:
    enc = tiktoken.get_encoding(name)
except Exception:
    fail("cache" if mode == "count" else "download")
if mode == "count":
    texts = json.load(sys.stdin)
    print(json.dumps({"counts": [len(enc.encode(t, disallowed_special=())) for t in texts]}))
else:
    print(json.dumps({"ok": True}))
"""

_token_lock = threading.Lock()
_token_counts = {}          # 글자 그대로 -> 토큰 수. TOKEN_CACHE_MAX 넘으면 오래된 것부터 버린다
_token_failed = (0.0, "")   # (실패한 시각, 상태). 폴링(2초)마다 프로세스를 새로 띄우지 않으려고 잠시 기억


def _tokenizer_python():
    py = os.path.join(TOKENIZER_VENV, "bin", "python")
    return py if os.access(py, os.X_OK) else None


NET_ENV = {"HOME", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR",
           "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}


def _run_tokenizer(mode, texts=None, timeout=30):
    """-> (결과 dict 또는 None, 실패 상태: setup / import / cache / download / error)."""
    py = _tokenizer_python()
    if not py:
        return None, "setup"
    # 키 같은 환경변수가 하위 프로세스로 가지 않게 PATH만 넘긴다. 어휘를 내려받는 warm은 프록시·인증서만 더한다.
    keep = ["PATH"] + ([] if mode == "count" else [k for k in os.environ if k.upper() in NET_ENV])
    env = {k: os.environ[k] for k in keep if k in os.environ}
    try:
        p = subprocess.run([py, "-I", "-c", _TOKEN_SNIPPET, mode, TOKENIZER_CACHE, TOKEN_ENCODING],
                           input=json.dumps(texts or []), capture_output=True, text=True,
                           env=env, timeout=timeout)
        out = json.loads(p.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None, "error"
    if p.returncode != 0 or not isinstance(out, dict):
        return None, out.get("error", "error") if isinstance(out, dict) else "error"
    return out, ""


def count_tokens(texts):
    """-> (상태, {글자: 토큰 수}). 상태가 "ok"가 아니면 수는 비어 있다. 한 번에 모아서 센다."""
    global _token_failed
    texts = set(texts)
    with _token_lock:
        got = {t: _token_counts[t] for t in texts if t in _token_counts}
        missing = [t for t in texts if t not in got]
        if missing:
            when, state = _token_failed
            if state and time.time() - when < TOKEN_FAIL_SECONDS:
                return state, {}
            out, state = _run_tokenizer("count", missing)
            if out is None or len(out.get("counts", [])) != len(missing):
                _token_failed = (time.time(), state or "error")
                return _token_failed[1], {}
            _token_failed = (0.0, "")
            for t, n in zip(missing, out["counts"]):
                got[t] = _token_counts[t] = n
            while len(_token_counts) > TOKEN_CACHE_MAX:
                _token_counts.pop(next(iter(_token_counts)))
        elif not _tokenizer_python():
            return "setup", {}
        return "ok", got


def token_setup_command():
    """이 서버가 쓰는 데이터 폴더에 맞는, 사용자가 그대로 칠 setup 명령."""
    if brew_prefix():
        return "agent-hud tokens setup"
    cmd = f"python3 {shlex.quote(os.path.abspath(__file__))} tokens setup"
    return f"AGENT_HUD_HOME={shlex.quote(TOOL_DIR)} {cmd}" if os.environ.get("AGENT_HUD_HOME") else cmd


def _loaded_count(rows):
    """이 프로젝트에서 Claude Code가 실제로 읽는 스킬 수.

    스킬은 본문이 아니라 **이름과 설명이 세션 시작 때 전부** 컨텍스트에 올라간다
    (agentskills.io 명세의 progressive disclosure). 그래서 안 쓰는 스킬도 비용이다.
    꺼진 플러그인의 스킬은 빠진다. permissions.deny로 차단한 스킬은 목록에 남으므로
    빼지 않는다(센티널 실측, ADR 10).
    """
    return sum(1 for row in rows for sk in row["skills"]
               if not _claude_off(row, sk) and "Claude Code" in (sk.get("agents") or []))


def _claude_off(row, sk):
    """Claude Code가 시작할 때 설명을 읽지 않는 스킬: 꺼진 플러그인, skillOverrides로 끈 스킬,
    머리말의 disable-model-invocation. 다른 에이전트는 상관없다."""
    return row["enabled"] is False or sk.get("enabled") is False or bool(sk.get("manual_only"))


def _attach_tokens(rows):
    """모든 스킬에 sk["tokens"](없으면 None)를 달고 요약을 돌려준다. 에이전트별 수는 지금 설정에서
    그 에이전트가 볼 수 있는 스킬이고(못 센 것도 든다), 세션에서 실제로 올라간 양이 아니다. 같은 SKILL.md는 한 번만 센다."""
    skills = [(row, sk) for row in rows for sk in row["skills"]]
    text = {id(sk): None if {i["code"] for i in sk.get("issues", [])} & set(TOKEN_INCOMPLETE)
            else sk["name"] + "\n" + sk["desc"] for _, sk in skills}
    state, counts = count_tokens([t for t in text.values() if t is not None])
    seen = {}
    for row, sk in skills:
        sk["tokens"] = counts.get(text[id(sk)])
        e = seen.setdefault(os.path.realpath(os.path.join(sk["path"], "SKILL.md")),
                            {"tokens": sk["tokens"], "agents": set()})
        e["agents"] |= {a for a in sk["agents"] if not (a == "Claude Code" and _claude_off(row, sk))}
    measured = [e for e in seen.values() if e["tokens"] is not None]
    # skills는 볼 수 있는 스킬 전부(못 센 것 포함), measured는 그중 센 것, tokens는 센 것만의 합이다.
    per_agent = {}
    for a in SKILL_AGENTS:
        have = [e for e in seen.values() if a in e["agents"]]
        got = [e for e in have if e["tokens"] is not None]
        per_agent[a] = {"skills": len(have), "measured": len(got),
                        "tokens": sum(e["tokens"] for e in got) if state == "ok" else None}
    return {"encoding": TOKEN_ENCODING, "state": state, "setup": token_setup_command(),
            "skills": len(seen), "measured": len(measured),
            "total": sum(e["tokens"] for e in measured) if state == "ok" else None, "agents": per_agent}


def _section_state(skills):
    """에이전트별로 all / some / none. 교집합만 쓰면 12개 중 3개가 막혔을 때
    나머지 9개가 멀쩡한데도 섹션 전체가 '못 봄'으로 보인다."""
    sets = [set(sk["agents"]) for sk in skills]
    out = {}
    for a in SKILL_AGENTS:
        n = sum(1 for x in sets if a in x)
        out[a] = "all" if sets and n == len(sets) else ("some" if n else "none")
    return out


def _skills_disabled_elsewhere(project_dir):
    """다른 에이전트가 자기 설정으로 끈 스킬 -> (Codex SKILL.md 경로, {에이전트: 스킬 이름}).
    HUD는 읽기만 한다. Codex는 ~/.codex/config.toml, Gemini CLI는 사용자·작업 폴더 settings.json의
    skills.disabled, Copilot은 사용자·저장소 settings.json의 disabledSkills(각 공식 문서)."""
    paths = set()
    try:
        import tomllib      # Python 3.11부터. 없으면 Codex 설정은 못 읽는다.
        home = os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")
        with open(os.path.join(home, "config.toml"), "rb") as f:
            entries = ((tomllib.load(f).get("skills") or {}).get("config")) or []
        paths = {os.path.realpath(os.path.expanduser(e["path"])) for e in entries
                 if isinstance(e, dict) and e.get("enabled") is False and isinstance(e.get("path"), str)}
    except (ImportError, OSError, ValueError, AttributeError) as e:
        if not isinstance(e, (ImportError, FileNotFoundError)):
            print(f"Codex 설정을 읽지 못했습니다: {e}", file=sys.stderr)
    def names(path, *keys):
        v = read_json(path, {})
        for k in keys:
            v = v.get(k) if isinstance(v, dict) else None
        return {x for x in v if isinstance(x, str)} if isinstance(v, list) else set()
    gem = names(os.path.join(HOME, ".gemini", "settings.json"), "skills", "disabled") | \
        names(os.path.join(project_dir, ".gemini", "settings.json"), "skills", "disabled")
    cop = names(os.path.join(HOME, ".copilot", "settings.json"), "disabledSkills") | \
        names(os.path.join(project_dir, ".github", "copilot", "settings.json"), "disabledSkills")
    return paths, {"Gemini CLI": gem, "Copilot": cop}


def _skill_root_index(project_dir):
    """스킬 폴더들을 훑어 {이름: (볼 수 있는 에이전트, 어느 폴더)}."""
    found = {}
    for rel, agents in SKILL_ROOTS_PROJECT:
        _scan_skill_root(os.path.join(project_dir, rel.replace("/", os.sep)), rel, agents, found)
    for rel, agents in SKILL_ROOTS_HOME:
        _scan_skill_root(os.path.join(HOME, rel.replace("/", os.sep)), "~/" + rel, agents, found)
    plugins = os.path.join(HOME, ".gemini", "antigravity-cli", "plugins")
    for name in sorted(os.listdir(plugins)) if os.path.isdir(plugins) else []:
        rel = f".gemini/antigravity-cli/plugins/{name}/skills"
        _scan_skill_root(os.path.join(HOME, rel.replace("/", os.sep)), "~/" + rel, ["Antigravity"], found)
    return found


def collect_skills(ctx):
    """스킬 한 탭. 플러그인이 준 것과 단독으로 놓인 것을 한 화면에 둔다 --
    사용자에게 그 둘은 '스킬'이라는 한 가지이고, 출처만 다르다."""
    project_dir = default_project_dir(ctx)
    index = _skill_root_index(project_dir)
    sources = skill_sources(project_dir)
    codex_off, by_name_off = _skills_disabled_elsewhere(project_dir)
    enabled, has_local = plugin_state(project_dir)
    installed = read_json(os.path.join(CLAUDE_DIR, "plugins", "installed_plugins.json")).get("plugins", {})
    marketplaces = read_json(os.path.join(CLAUDE_DIR, "plugins", "known_marketplaces.json"))
    sets = read_sets()

    def decorate(skill, fallback_agents):
        hit = index.get(skill["id"])
        agents = hit["agents"] if hit else list(fallback_agents)
        real_md = os.path.realpath(os.path.join(skill["path"], "SKILL.md"))
        agents = [a for a in agents if not ((a == "Codex" and real_md in codex_off) or skill.get("name") in by_name_off.get(a, ()))]
        skill["agents"] = agents
        skill["missing"] = [a for a in SKILL_AGENTS if a not in agents]
        skill["roots"] = hit["roots"] if hit else []
        skill["shared"] = skill_is_shared(project_dir, skill["id"], sources.get(skill["id"]))
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
            sk["manual_only"] = _manual_only(os.path.join(sk["path"], "SKILL.md"))
        rows.append({
            "name": name,
            "section_state": _section_state(skills),
            "components": plugin_components(install_path),
            "version": entry.get("version", "?"),
            "enabled": bool(enabled.get(name, False)),
            "modes": [m for m, v in sets.items() if name in v["plugins"]],
            "source": mp_src.get("repo") or mp_src.get("path") or mp_name or "?",
            "skills": skills,
        })

    # 플러그인에 속하지 않은 스킬들. Claude Code가 읽는 것에는 스위치가 있다(skillOverrides).
    plugin_ids = {sk["id"] for r in rows for sk in r["skills"]}
    overrides = skill_overrides(project_dir)[0]
    loose = []
    for sid, hit in _loose_entries(index, plugin_ids):
        name, desc, issues = _skill_meta(hit["path"], sid)
        sk = decorate({"id": sid, "name": name, "desc": desc, "issues": issues,
                       "path": os.path.dirname(hit["path"])}, [])
        if "Claude Code" in sk["agents"]:
            sk["override"] = overrides.get(name) if overrides.get(name) in SKILL_OVERRIDE_VALUES else "on"
            sk["enabled"] = sk["override"] not in SKILL_HIDDEN
            sk["manual_only"] = _manual_only(hit["path"])
        loose.append(sk)
    if loose:
        rows.append({
            "name": "", "version": "", "enabled": None,
            "section_state": _section_state(loose),
            "modes": [], "source": ", ".join(sorted({r for sk in loose for r in sk["roots"]})),
            "skills": loose,
        })

    tokens = _attach_tokens(rows)
    return {
        "title": "Skills (who can see them)",
        "rows": rows,
        "agents": SKILL_AGENTS,
        "loaded": _loaded_count(rows),
        "tokens": tokens,
        "load": session_load(project_dir, tokens),
        "has_local": has_local,
        "project_dir": project_dir,
        "known_projects": known_projects(),
        "worktrees": collect_worktrees(project_dir),
    }


def collect_instructions(ctx):
    project_dir = default_project_dir(ctx)
    rows = [
        _file_row(os.path.join(CLAUDE_DIR, "CLAUDE.md"), os.path.join(CLAUDE_DIR, "CLAUDE.md")),
        _file_row(os.path.join(HOME, ".codex", "AGENTS.md"), os.path.join(HOME, ".codex", "AGENTS.md"), "Codex"),
        _file_row(os.path.join(HOME, ".gemini", "GEMINI.md"), os.path.join(HOME, ".gemini", "GEMINI.md"), "Gemini CLI"),
        _file_row("CLAUDE.md", os.path.join(project_dir, "CLAUDE.md")),
    ]
    sub_rows, truncated = _instruction_rows(project_dir)
    rows = _with_link_targets(rows + sub_rows)
    excludes = claude_md_excludes(project_dir)
    claude_reads = session_instructions(project_dir)["Claude Code"]
    seen_real = {os.path.realpath(r["path"]) for r in rows}
    # 위 목록이 안 훑는 곳: 상위 폴더, .claude/ 안, 규칙 폴더
    rows += [_file_row(f, f) for f in claude_reads if f not in seen_real]
    for r in rows:   # 어느 칸에 그릴지: 이 프로젝트 안이면 project, 아니면 이 컴퓨터 전체
        r["scope"] = "project" if r["path"].startswith(project_dir.rstrip(os.sep) + os.sep) else "global"
        # 직접 제외했거나, 제외된 파일의 @대상으로만 닿는 파일. 다른 에이전트가 읽는 것과는 별개다.
        # 다른 도구의 파일은 그 경로를 직접 제외했을 때만이다. 링크 대상이 제외돼도 Claude Code와는 무관하다.
        direct = (_claude_excluded(r["path"], excludes) if r["tool"] in ("Claude Code", "")
                  else any(p.fullmatch(r["path"]) for p in excludes))
        r["claude_excluded"] = direct or (bool(r.get("via")) and os.path.realpath(r["path"]) not in claude_reads)
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
    data = read_json(os.path.join(project_dir, LOCAL_SETTINGS), {})
    data.setdefault("enabledPlugins", {}).update({k: bool(v) for k, v in changes.items()})
    return _write_local(project_dir, data)


def _write_local(project_dir, data):
    path = os.path.join(project_dir, LOCAL_SETTINGS)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return False, str(e)
    return True, ""


# 플러그인 밖 스킬(사용자·프로젝트 스킬)은 skillOverrides로 목록에서 뺄 수 있다. 이 두 값이면
# 빠지는 것을 Claude Code로 직접 확인했다(ADR 10, tests/manual/skill_visibility.sh). 플러그인
# 스킬에는 듣지 않아서 플러그인은 여전히 통째로 끈다.
SKILL_HIDDEN = ("off", "user-invocable-only")
SKILL_OVERRIDE_VALUES = ("on", "name-only", "user-invocable-only", "off")


def _manual_only(skill_md):
    """SKILL.md 머리말의 disable-model-invocation: true. 사용자가 /이름 으로 부를 때만 읽히는 스킬이다."""
    try:
        with open(skill_md, encoding="utf-8") as f:
            head = f.read(META_READ_MAX)
    except OSError:
        return False
    body = head.split("\n---", 1)[0]
    return re.search(r"^disable-model-invocation:\s*true\s*$", body, re.M) is not None


def skill_overrides(project_dir):
    """-> (실제로 적용되는 값, 공유 settings.json의 값). 로컬이 공유를 이긴다(직접 확인)."""
    shared = read_json(os.path.join(project_dir, ".claude", "settings.json")).get("skillOverrides")
    local = read_json(os.path.join(project_dir, LOCAL_SETTINGS)).get("skillOverrides")
    shared = shared if isinstance(shared, dict) else {}
    local = local if isinstance(local, dict) else {}
    return {**shared, **local}, shared


def _loose_entries(index, plugin_ids):
    return [(sid, hit) for sid, hit in sorted(index.items()) if sid not in plugin_ids]


def loose_claude_skills(project_dir):
    """이 프로젝트에서 Claude Code가 읽는 플러그인 밖 스킬 -> {스킬 이름: 폴더 이름}."""
    plugin_ids = {sid for skills in plugin_skills().values() for sid in skills}
    out = {}
    for sid, hit in _loose_entries(_skill_root_index(project_dir), plugin_ids):
        if "Claude Code" in hit["agents"]:
            out[_skill_meta(hit["path"], sid)[0]] = sid
    return out


def set_skill_overrides(changes, project_dir):
    """{스킬 이름: bool 또는 skillOverrides 값}을 이 프로젝트의 settings.local.json에 쓴다.
    켤 때는 키를 지우고, 공유 설정이 끄고 있을 때만 "on"을 써서 이긴다."""
    if not project_dir or not os.path.isdir(project_dir):
        return False, "project not found"
    changes = {n: ("on" if v else "off") if isinstance(v, bool) else v for n, v in changes.items()}
    bad = [n for n, v in changes.items() if v not in SKILL_OVERRIDE_VALUES]
    if bad:
        return False, "unknown value for: " + ", ".join(bad[:3])
    unknown = [n for n in changes if n not in loose_claude_skills(project_dir)]
    if unknown:
        return False, "unknown skill: " + ", ".join(unknown[:3])
    shared = skill_overrides(project_dir)[1]
    data = read_json(os.path.join(project_dir, LOCAL_SETTINGS), {})
    ov = data.get("skillOverrides") if isinstance(data.get("skillOverrides"), dict) else {}
    for name, value in changes.items():
        if value != "on":
            ov[name] = value
        elif shared.get(name) in SKILL_HIDDEN:
            ov[name] = "on"
        else:
            ov.pop(name, None)
    if ov:
        data["skillOverrides"] = ov
    else:
        data.pop("skillOverrides", None)
    return _write_local(project_dir, data)


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
        write_json(MODES_FILE, sets, ensure_ascii=False, indent=2)
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


def _local_switches(project_dir):
    data = read_json(os.path.join(project_dir, LOCAL_SETTINGS), {})
    return {k: dict(data.get(k)) if isinstance(data.get(k), dict) else {} for k in ("enabledPlugins", "skillOverrides")}


def _record_group_writes(saved, pre, post):
    """그룹이 이번에 바꾼 키만 {적용 전 값, 그룹이 쓴 값}으로 적는다. 그룹이 쓴 값을 사용자가 바꿨으면 그 키는 사용자 것이다."""
    for section in ("enabledPlugins", "skillOverrides"):
        entries = saved.setdefault(section, {})
        for key in set(pre[section]) | set(post[section]) | set(entries):
            old, new, e = pre[section].get(key), post[section].get(key), entries.get(key)
            if old != new:
                entries[key] = {"before": e["before"] if e and e["wrote"] == old else old, "wrote": new}
            elif e and e["wrote"] != old:
                del entries[key]


def _restore_switches(project_dir, saved):
    """그룹이 쓴 값이 그대로인 키만 적용 전 값으로 되돌린다."""
    data = read_json(os.path.join(project_dir, LOCAL_SETTINGS), {})
    for section in ("enabledPlugins", "skillOverrides"):
        cur = data.get(section) if isinstance(data.get(section), dict) else {}
        for key, e in saved.get(section, {}).items():
            if cur.get(key) != e["wrote"]:
                continue
            if e["before"] is None:
                cur.pop(key, None)
            else:
                cur[key] = e["before"]
        if cur:
            data[section] = cur
        else:
            data.pop(section, None)
    return _write_local(project_dir, data)


def assign_set(name, project_dir):
    """세트를 프로젝트에 적용한다. 스킬 링크도 플러그인 on/off도 이 프로젝트에만 걸린다
    (플러그인은 settings.local.json의 enabledPlugins에 쓴다).
    name이 빈 문자열이면 이 프로젝트의 배정을 풀고 플러그인과 스킬 스위치를 적용 전 값으로 되돌린다."""
    if not project_dir or not os.path.isdir(project_dir):
        return False, "project not found"
    sets = read_sets()
    if name and name not in sets:
        return False, "unknown set"
    restore_file = SETS_FILE + ".restore"
    restore = read_json(restore_file, {})
    saved = restore.get(project_dir)
    if name and saved is None:
        saved = restore[project_dir] = {}
    pre = _local_switches(project_dir)

    # 1) 스킬: 이 세트 것만 남긴다. 어느 세트에도 없는 스킬 링크는 사용자가 직접 건 것이므로 둔다.
    wanted = set(sets.get(name, {}).get("skills", [])) if name else set()
    managed = {sk for v in sets.values() for sk in v["skills"]}
    errors = []
    for sk in sorted(managed):
        ok, err = link_skill(sk, sk in wanted, project_dir)
        if not ok and sk in wanted:
            errors.append(f"{sk}: {err}")

    # 2) 플러그인: 해제는 아래에서 적용 전 값으로 되돌린다.
    if name:
        # 설치된 플러그인 전부에 값을 적는다. 하나라도 빠뜨리면 그건 전역 값을 물려받아
        # "왜 이게 켜져 있지"가 된다.
        members = set(sets[name]["plugins"])
        ok, err = set_plugins({pl: pl in members for pl in known_plugin_names()}, project_dir)
        if not ok:
            errors.append(err)
        # 플러그인 밖 스킬도 같은 규칙: 그룹에 있으면 켜고 없으면 끈다. 1)에서 건 링크까지 본 뒤에 센다.
        loose = loose_claude_skills(project_dir)
        if loose:
            ok, err = set_skill_overrides({nm: nm in wanted or sid in wanted for nm, sid in loose.items()},
                                          project_dir)
            if not ok:
                errors.append(err)

    if name:
        _record_group_writes(saved, pre, _local_switches(project_dir))
    elif saved is not None:
        ok, err = _restore_switches(project_dir, saved)
        if ok:
            restore.pop(project_dir, None)
        else:       # 다시 해제하면 복원할 수 있게 기록을 둔다
            errors.append(err)
    if name or saved is not None:
        try:
            write_json(restore_file, restore, ensure_ascii=False, indent=2)
        except Exception as e:
            errors.append(str(e))

    assigned = read_json(SETS_FILE, {})
    if name:
        assigned[project_dir] = name
    else:
        assigned.pop(project_dir, None)
    try:
        write_json(SETS_FILE, assigned, ensure_ascii=False, indent=2)
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
<link rel="manifest" href="/manifest.json">
<style>
/* 팔레트: GitHub Primer 토큰을 그대로 쓰고 있던 걸 우리 값으로 교체(2026-09).
   변수 이름·개수는 그대로, 값만 바꿨다 -- getdesign.md의 PostHog/OpenCode/Linear
   DESIGN.md를 참고해 올리브 쪽으로 따뜻한 중성색 + 황토 accent 하나로.
   중성색을 분홍 쪽(#faf9f5 계열)으로 두면 Claude 브랜드와 사촌이 된다. 이 도구는
   서드파티 개인 프로젝트라 그렇게 보이면 안 된다. */
:root{
  --bg:#eeefe9;--panel:#ffffff;--border:#d3d6ca;--text:#23251d;--dim:#6c6e63;
  --accent:#836313;--on:#2f7a4f;--off:#62655a;--on-tint:#e6f2ea;--off-tint:#e7e9df;--accent-tint:#f6efd9;
  --shadow:0 1px 2px rgba(35,37,29,.05),0 1px 6px rgba(35,37,29,.04);
}
:root[data-theme="dark"]{
  --bg:#14150f;--panel:#1c1e17;--border:#2c2e25;--text:#eceee4;--dim:#8f9284;
  --accent:#e8bb4e;--on:#6bbf8a;--off:#8f9284;--on-tint:rgba(107,191,138,.13);--off-tint:rgba(143,146,132,.11);--accent-tint:rgba(232,187,78,.14);
  --shadow:0 1px 2px rgba(0,0,0,.34),0 1px 6px rgba(0,0,0,.26);
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,"SF Pro Text","Pretendard",Inter,sans-serif;margin:0;padding:0;-webkit-font-smoothing:antialiased}
.page{display:flex;align-items:flex-start;max-width:1180px;margin:0 auto}
.main{flex:1;min-width:0;padding:28px 28px 28px 18px}
.sidebar{flex:0 0 220px;padding:28px 12px 28px 28px;position:sticky;top:0;align-self:flex-start;max-height:100vh;overflow-y:auto;display:flex;flex-direction:column;gap:14px}
.sb-list{display:flex;flex-direction:column;gap:14px;min-width:0}
.sb-search{display:flex;align-items:center;gap:7px;border:1px solid var(--border);border-radius:8px;padding:7px 9px;background:var(--panel)}
.sb-search svg{flex-shrink:0;color:var(--dim)}
.sb-search input{border:0;background:transparent;outline:0;font:inherit;font-size:12.5px;color:var(--text);width:100%}
.sb-search input::placeholder{color:var(--dim)}
.sb-group{display:flex;flex-direction:column;gap:2px}
.sb-label{font-size:10.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--dim);padding:4px 8px 2px}
.sb-item{display:flex;align-items:center;gap:8px;padding:7px 8px;border-radius:7px;cursor:pointer;font-size:13px;color:var(--text);position:relative}
.sb-item:hover{background:var(--off-tint)}
.sb-item.active{background:var(--accent-tint);color:var(--accent);font-weight:600}
.sb-item.active::before{content:"";position:absolute;left:-11px;top:6px;bottom:6px;width:3px;border-radius:2px;background:var(--accent)}
.sb-dot{width:6px;height:6px;border-radius:50%;background:var(--on);flex-shrink:0}
.sb-dot.idle{background:var(--dim);opacity:.5}
.sb-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.sb-parent{color:var(--dim);font-size:11px;font-weight:400;flex-shrink:0}
.sb-pin{margin-left:auto;background:none;border:0;padding:2px;color:var(--dim);cursor:pointer;opacity:0;flex-shrink:0;line-height:0}
.sb-item:hover .sb-pin{opacity:1}
.sb-item.active .sb-pin{opacity:1;color:var(--accent)}
.sb-item.pinned .sb-pin{opacity:1;color:var(--accent)}
.sb-item .sb-pin.sb-rm{margin-left:0;font-size:14px;line-height:1;opacity:0;color:var(--dim)}
.sb-item:hover .sb-pin.sb-rm{opacity:1}
.sb-empty{font-size:12px;color:var(--dim);padding:6px 8px}
.sb-add{font-size:12px;font-weight:600;color:var(--accent);cursor:pointer;padding:0 8px}
.sb-add:hover{opacity:.75}
@media (max-width:640px){
  .page{flex-direction:column}
  .sidebar{position:static;width:100%;padding:16px;max-height:none;border-bottom:1px solid var(--border)}
  .main{padding:16px}
}
h1{margin:0;font-size:23px;font-weight:600;letter-spacing:-.03em;line-height:1.1;color:var(--text)}
.hdr{display:grid;grid-template-columns:1fr auto;align-items:center;gap:6px 16px;margin-bottom:20px}
.hdr-ctl{display:flex;gap:8px;align-items:center;flex-shrink:0;white-space:nowrap}
.seg{display:inline-flex;height:28px;border:1px solid var(--border);border-radius:8px;overflow:hidden;font-size:12px;font-weight:600}
#h1sub{grid-column:1/-1;display:block;font-size:13px;line-height:1.5;color:var(--dim)}
.hl-title{margin-bottom:4px}
.hl-row{display:grid;grid-template-columns:110px 90px 90px auto;gap:0 14px;font-variant-numeric:tabular-nums}
.hl-agent{color:var(--text);font-weight:600}
.hl-tok{color:var(--text);font-weight:700}
.rule-note{border-left:2px solid var(--border);padding:2px 0 2px 10px;margin-bottom:14px;
  color:var(--dim);font-size:12px;line-height:1.6}
.rule-note b{color:var(--text);font-weight:600}
#h1sub:lang(ko){font-family:inherit}
#h1sub b{color:var(--text);font-weight:700}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));grid-auto-flow:dense;gap:12px}
.card{background:var(--panel);border:1px solid var(--border);box-shadow:var(--shadow);border-radius:8px;padding:14px}
.card.wide{grid-column:1/-1}
.empty{color:var(--dim);font-size:13px;padding:6px 0;display:flex;align-items:center;gap:8px}
.card h2{font-size:11px;color:var(--dim);margin:0 0 10px;font-weight:600;letter-spacing:.09em;text-transform:uppercase}
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
.switch{display:inline-flex;align-items:center;justify-content:center;min-width:44px;text-align:center;font-size:11px;font-weight:600;letter-spacing:.02em;padding:3px 8px;border-radius:4px;cursor:pointer;flex:0 0 auto;user-select:none;transition:background .12s,color .12s,transform .12s}
.sw-on.switch:hover{background:var(--on);color:var(--panel);border-color:var(--on)}
.sw-off.switch:hover{background:var(--accent);color:var(--bg);border-color:var(--accent)}
.switch:active{transform:scale(.96)}
.switch.busy{opacity:.4;cursor:wait}
.lang-opt{display:inline-flex;align-items:center;padding:0 11px;cursor:pointer;color:var(--dim);transition:background .12s,color .12s;font-size:12px}
.lang-opt:hover{color:var(--text)}
.lang-opt.active{background:var(--accent);color:var(--bg)}
.quiet-toggle .lang-opt.active{background:var(--off-tint);color:var(--text)}
.tab-opt{padding:7px 14px;cursor:pointer;color:var(--dim);font-size:13px;font-weight:600;transition:background .12s,color .12s}
.tab-opt:not(:last-child){border-right:1px solid var(--border)}
.tab-opt:hover{color:var(--text)}
.tab-opt.active{background:var(--accent);color:var(--bg)}
.sw-on{background:var(--on-tint);color:var(--on);border:1px solid color-mix(in srgb,var(--on) 35%,transparent)}
.sw-off{background:var(--off-tint);color:var(--off);border:1px solid var(--border)}
.sw-manual{background:transparent;color:var(--dim);border:1px dashed var(--dim)}
.guide{margin:0 0 18px;padding:0 2px;font-size:11px;line-height:1.5;color:var(--dim);opacity:.85}
.loadline.loadline-off{background:transparent;border-color:transparent;padding-left:0;padding-right:0}
.loadline-off .note{margin-top:2px}
.guide-row{display:flex;gap:8px;align-items:baseline;margin-top:3px}
.guide-row b{flex:0 0 auto;font-weight:600;color:var(--dim)}
.guide-row b::after{content:' ·'}
.help{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:50%;border:1px solid var(--border);color:var(--dim);font-size:10px;font-weight:700;cursor:pointer;margin-left:4px;flex-shrink:0}
.help:hover{color:var(--text);border-color:var(--accent)}
.help-box{margin:2px 0 8px;font-size:11.5px}
.note{color:var(--dim);font-size:12px;margin-top:6px;line-height:1.65;text-wrap:pretty}
.clickable{cursor:pointer}
.row.clickable:hover{background:var(--off-tint)}
span.clickable:hover,div.skill-desc.clickable:hover{color:var(--accent)}
.content{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px;margin:6px 0 10px;font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:12px;max-height:360px;overflow:auto;display:none}
.content.open{display:block}
.badge{background:var(--accent);color:var(--bg);padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600}
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
  border-radius:6px;padding:8px 11px;margin:2px 0 10px;cursor:help;line-height:1.6;font-variant-numeric:tabular-nums}
.warn{margin-left:8px;padding:1px 7px;border-radius:4px;font-size:10.5px;font-weight:600;
  background:var(--off-tint);color:var(--text);cursor:help;white-space:nowrap;vertical-align:middle}
.comp{color:var(--dim);font-size:11px;white-space:nowrap;cursor:help;font-variant-numeric:tabular-nums;
  font-family:ui-monospace,"SF Mono",Menlo,monospace;border-bottom:1px dotted var(--border)}
.comp:hover{color:var(--text);border-bottom-color:var(--dim)}
.tooltag{border:1px solid var(--border);color:var(--dim);padding:1px 7px;border-radius:999px;font-size:11px;white-space:nowrap;margin-left:8px}
.tag{font-size:11px;color:var(--dim);font-family:ui-monospace,"SF Mono",Menlo,monospace;white-space:nowrap;font-variant-numeric:tabular-nums}
.tag.danger{cursor:pointer}
.tag.danger:hover{color:#f04452}
.mono{font-family:ui-monospace,"SF Mono",Menlo,monospace}
.card-action{font-size:12px;font-weight:600;color:var(--accent);cursor:pointer;white-space:nowrap}
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
#installWrap{position:relative}
#installBtn{background:transparent;color:var(--dim);border:1px solid var(--border);height:28px;
  border-radius:8px;padding:0 11px;font-size:12px;font-weight:600;white-space:nowrap;
  font-family:inherit;cursor:pointer}
#installBtn:hover{color:var(--text);border-color:var(--accent)}
#installPop{display:none;position:absolute;top:calc(100% + 6px);right:0;z-index:10;width:230px;
  background:var(--panel);border:1px solid var(--border);border-radius:8px;box-shadow:var(--shadow);
  padding:10px 12px;font-size:12px;line-height:1.6;color:var(--text)}
#installPop.open{display:block}
</style></head><body>
<div class="page">
<aside class="sidebar" id="sidebar"></aside>
<main class="main">
<div class="hdr">
  <span>
    <span style="display:flex;align-items:center;gap:8px">
      <svg width="22" height="22" viewBox="0 0 96 96" aria-hidden="true" style="flex-shrink:0">
        <defs><clipPath id="hullMark"><circle cx="48" cy="48" r="23"/></clipPath></defs>
        <rect x="25" y="52" width="46" height="22" fill="var(--accent)" clip-path="url(#hullMark)"/>
        <circle cx="48" cy="48" r="23" fill="none" stroke="currentColor" stroke-width="6"/>
        <line x1="15" y1="52" x2="81" y2="52" stroke="currentColor" stroke-width="6" stroke-linecap="round"/>
      </svg>
      <h1>Agent HUD</h1>
    </span>
  </span>
  <span class="hdr-ctl">
    <span id="installWrap">
      <button id="installBtn"></button>
      <div id="installPop"></div>
    </span>
    <span id="langToggle" class="seg">
      <span id="langEn" class="lang-opt">EN</span><span id="langKo" class="lang-opt">한국어</span>
    </span>
    <span id="themeToggle" class="seg quiet-toggle">
      <span id="themeLight" class="lang-opt">☀</span><span id="themeDark" class="lang-opt">☾</span>
    </span>
  </span>
  <span id="h1sub"></span>
</div>
<div class="note" id="updateBanner" style="margin-bottom:12px;display:none"></div>
<div id="tabs" style="display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:12px"></div>
<div id="applyBanner" class="rule-note"></div>
<div class="grid" id="app"></div>
<div style="max-width:920px;margin-top:16px"><a id="fbLink" class="card-action" href="#" target="_blank" rel="noopener"></a></div>
<div id="ts"><span id="tsText"></span><select id="period" title=""></select></div>
</main>
</div>
<script>
const T = {
  en: {
  wt_title: 'Other checkouts of this repository (worktrees)',
  wt_intro: 'A worktree is the same repository checked out into another folder, usually for working on a second branch at the same time. Skills added here do not carry over by themselves. Pick the skills to share; plugins, hooks, agents and settings are left alone, and existing folders and links are kept.',
  wt_root_only: 'Select the repository checkout root to apply skills. Subfolder configurations stay local to that folder.',
  wt_query_failed: 'Could not read the Git worktree list.',
  wt_skills: 'Skills to share', wt_targets: 'Choose worktrees',
  wt_preview: 'Preview', wt_apply: 'Add missing skills',
  wt_auto_on: 'Save and enable for new worktrees', wt_auto_off: 'Disable automatic application',
  wt_auto_active: 'Automatic application is enabled. Saving a new default affects future worktrees only.',
  wt_auto_inactive: 'Automatic application is off. Existing skills remain when you disable it.',
  wt_poll: n => `While HUD is running, new worktrees are checked every ${n} seconds. The first session may start before application finishes.`,
  wt_session: 'These are file states, not a live session skill list. Codex detects skill changes; confirm with /skills. Claude may need /reload-skills if this directory did not exist at session start.',
  wt_claude: 'Creating .claude/skills can stop newer Claude Code from reading the main checkout’s skills. Choose .agents/skills only if you want to share with Codex alone.',
  wt_confirm: 'Add only missing skills at the paths in this preview? Conflicts and existing files are kept. The target is checked again before writing.',
  wt_auto_confirm: 'Save this selection as the repository default for future worktrees? Existing worktrees are unchanged. No skills are deleted.',
  wt_override_confirm: 'Save this worktree’s automatic application choice? A custom choice uses the skills and directories selected above. Existing skills are kept.',
  wt_inherit: 'Repository default', wt_exclude: 'Exclude from automatic application', wt_custom: 'Use selection above',
  wt_mode_inherit: 'Default', wt_mode_exclude: 'Excluded', wt_mode_custom: 'Custom',
  wt_saved: 'Saved', wt_unavailable: 'Unavailable or unchecked', wt_detached: 'detached HEAD',
  wt_preview_needed: 'Select skills and worktrees, then preview the result.',
  wt_created: 'Added', wt_linked: 'Connected', wt_original: 'Source folder',
  wt_missing: 'Missing', wt_broken: 'Broken link', wt_conflict: 'Different source',
  wt_occupied: 'Existing file or folder', wt_blocked: 'Linked or inaccessible directory',
  wt_source_missing: 'Source unavailable', wt_choose: 'Choose at least one skill, directory and worktree.',
  wt_applied_at: at => `Last automatic application: ${new Date(at*1000).toLocaleString()}`,
  wt_state_note: 'Worktree status below reflects the saved configuration. Changing checkboxes only affects the preview.',
  wt_detail: 'Details', wt_skill_col: 'Skill', wt_source_detail: 'Source path',
    banner: 'The Always / Only when you type /name / Excluded switches apply from the <b>next session</b> the agent starts. Groups and the project list change right away.',
    headline_title: 'Read at the start of every session in this folder, and sent again with every message:',
    headline_none: 'Nothing is read at session start in this folder.',
    hl_instr: n => `${n} instruction file${n === 1 ? '' : 's'}`, hl_skills: n => `${n} skill${n === 1 ? '' : 's'}`,
    hl_tok: n => `about ${n.toLocaleString()} tokens`, hl_tok_na: 'tokens not counted',
    title_groups: 'Groups', title_instructions: 'Agent instructions', title_skills: 'Plugins & skills',
  guide_rows: [
    ['ALWAYS', 'The AI reads the name and description every session. Costs tokens each time.'],
    ['ONLY WHEN YOU TYPE /name', 'The AI does not know it exists until you type /name. Saves those tokens. (.claude/settings.local.json → skillOverrides: "user-invocable-only", same as disable-model-invocation: true in the skill, without editing it)'],
    ['EXCLUDED', 'The AI cannot use it in this project. (skillOverrides: "off")'],
  ],
  badge_on_tip: a => `${a} can use this skill in this project`,
  badge_off_tip: a => `${a} cannot find this skill in this project. Use "let other agents use it" to add it`,
  no_skills: 'No skills found in any known folder.',
  link_failed: 'Could not share that skill: ',
  loose_skills: 'Skills installed without a plugin',
    set_apply: 'Apply to this project', set_applied: 'Applied to this project',
    assign_confirm: (g, p, pl, sk) => `Apply "${g}" to this project?\n${p}\n\nALWAYS: ${pl}\n${sk} skill${sk===1?'':'s'} linked in\nEverything else: EXCLUDED (in this project only)`,
    unassign_confirm: (g, p) => `Stop applying "${g}" here?\n${p}\n\nThe linked skills are removed, and plugins and ALWAYS / EXCLUDED go back to what they were before. Values you changed yourself afterwards stay.`,
    kind_plugin: 'plugin', kind_skill: 'skill',
    add_member_ph: '+ add a plugin or skill…',
    member_plugin_tip: 'ALWAYS in this project',
    member_skill_tip: 'Linked into this project',
    assign_failed: 'Could not apply that group: ',
    on: 'ALWAYS', off: 'EXCLUDED', manual: 'ONLY WHEN YOU TYPE /name',
    remove: 'remove ✕', remove_tip: (m,g) => `take ${m} out of "${g}"`,
    remove_confirm: (m,g) => `Remove ${m} from group "${g}"?`,
    groups_guide: 'A group is a set of plugins and skills you switch on together. Pick a group for a project and every switch in it flips at once instead of one by one.',
    new_group: '+ create a new group', new_group_tip: 'e.g. one for coding, one for video',
    new_group_name_prompt: 'Name for the new group (e.g. "dev", "video"):',
    new_group_first_prompt: 'Which plugin should it start with?\n',
    no_groups: 'No groups yet. A group is the plugins and skills you switch on together, for example one for coding and one for video.',
  not_found: 'not found',
  claude_excluded: 'excluded from Claude Code',
  claude_excluded_tip: 'Claude Code does not read this file in this project (claudeMdExcludes). Other agents are not affected.',
  comp: {agents: 'agents', mcp: 'MCP', commands: 'commands', hooks: 'hooks', lsp: 'LSP',
    monitors: 'monitors', bin: 'binaries', settings: 'settings'},
  comp_count: (label, n) => `${n} ${label}`,
  comp_tip: n => `Also in this plugin: ${n}. Only skills can be shared with other agents`,
  share_to: names => 'let ' + names.join(', ') + ' use it too',
  share_short: 'let other agents use it',
  help_tip: 'How this works',
  share_done: 'every agent can use it',
  share_all_tip: 'When checked, a symlink to this skill is placed in the folders Codex, Cursor, Copilot, Gemini CLI and Antigravity look in inside this project (.agents/skills and others). No copy is made, the original stays put, and unchecking removes only the links. Claude Code reads it only while the plugin is on.',
  partly: a => `${a} can use only some of the skills in this plugin`,
  add_project: '+ add a folder', add_project_tip: 'Any folder. It does not have to be a git repository',
  add_project_prompt: 'Full path of the folder to add:',
  add_project_failed: 'Could not add that folder: ',
  no_project_yet: 'no folders yet',
  sidebar_search_ph: 'Search folders…',
  sidebar_favorites: 'Favorites', sidebar_recent: 'Recent', sidebar_all: 'All',
  sidebar_no_match: 'No folder matches that search',
  pin_tip: 'Pin to favorites', unpin_tip: 'Remove from favorites',
  forget_tip: 'Remove from this list',
  forget_confirm: p => `Remove this folder from the list?\n\n${p}\n\nThe folder and its settings stay as they are. It comes back when you run an agent session there.`,
  install_app: 'Install app',
  install_manual: 'This browser can’t install it automatically.<br><b>Chrome, Edge:</b> the install icon in the address bar.<br><b>Safari (macOS Sonoma+):</b> File → Add to Dock.',
  tok_head: (enc, total, n) => `About ${total.toLocaleString()} tokens of skill names and descriptions go into every session (${n} skills found, counted with ${enc})`,
  tok_head_part: (enc, total, m, n) => `About ${total.toLocaleString()} tokens from ${m} of the ${n} skills found (counted with ${enc}); the rest could not be counted, so this is less than the real total`,
  tok_head_none: n => `${n} skills found, but none of them could be counted`,
  tok_unmeasured: n => `${n} not counted: the name or description is missing, or the file could not be read`,
  tok_off: n => `${n} skills found · token counting is not set up yet`,
  tok_hint: {
    setup: 'Token counting is not set up yet. Run this once in a terminal:',
    import: 'The token counter is incomplete. Run setup again:',
    cache: 'The tokenizer vocabulary is not downloaded yet. Run setup:',
    download: 'The tokenizer vocabulary could not be downloaded. Check your network and run setup again:',
    error: 'Counting did not finish this time and will retry shortly. To reinstall the counter, use this command:'},
  tok_tip: 'An estimate of how much of the AI\'s memory the skill list takes at the start of a session. Only each skill\'s name and description are counted, not its contents, using the o200k_base tokenizer on this computer. It is not a bill or a provider\'s own number.',
  tok_skill: n => `${n.toLocaleString()} tok`,
  tok_skill_na: 'tok n/a', tok_skill_na_tip: 'This skill\'s name or description is missing or could not be read, so it is not counted.',
  spec_issue: 'format',
  issue: {
    unreadable: () => 'SKILL.md could not be read',
    no_frontmatter: () => 'No YAML frontmatter',
    frontmatter_unclosed: () => 'YAML frontmatter is not closed with ---',
    name_missing: () => 'name is missing',
    name_format: i => `name "${i.name}" — lowercase letters, digits and single hyphens only, max 64`,
    name_mismatch: i => `name "${i.name}" does not match its folder "${i.folder}"`,
    desc_missing: () => 'description is missing',
    desc_long: i => `description is ${i.len} characters (limit 1024)`,
  },
  scan_truncated: 'This project is large, so the scan stopped early. Some instruction files further down may be missing.',
  scope_global: 'This computer (every project)', scope_project: 'This project',
  agents_head: 'Subagents',
    no_subagents: 'No subagents',
    loading: 'loading…', error: 'error: ',
    toggle_failed: 'Could not switch that plugin: ', group_update_failed: 'Could not change the group: ',
    plugin_on_tip: 'The AI reads every skill in this plugin at the start of each session in this project. Click to exclude the plugin (from the next session)',
    plugin_off_tip: 'The AI cannot use this plugin in this project. Click to turn it back on (from the next session)',
    skill_on_tip: 'The AI reads this skill\'s name and description at the start of every session in this project. Click so it loads only when you type /name (from the next session)',
    skill_off_tip: 'The AI cannot use this skill in this project. Click to turn it back on (from the next session)',
    skill_manual_tip: 'The AI does not know this skill exists until you type /name in the chat. Click to exclude it (from the next session)',
    skill_manual_md_tip: 'This skill\'s own SKILL.md says disable-model-invocation: true, so it works this way in every project. Click to exclude it from this project (from the next session). To let the AI use it on its own, change that file',
    skill_toggle_failed: 'Could not switch that skill: ',
    skills_count: n => n + (n === 1 ? ' skill' : ' skills'),
    group_tag: g => 'group: ' + g,
    from: 'from: ',
    read_full_tip: 'Read the full description',
    no_skills_found: 'No skills',
    updated: 'updated ', every_n: n => `every ${n}s`, paused: 'paused',
    usage: (mb, cpu) => `${mb}MB` + (cpu === null ? '' : ` · ${cpu}% CPU`),
    period_tip: 'How often this page re-reads the files',
    switching: 'switching…',
    update_available: (v, latest, repo) => `↑ A new version is out: v${latest} (you're on v${v}) · <a href="https://github.com/${repo}/releases/latest" target="_blank" rel="noopener">what's new</a>`,
    update_now: 'Update now', update_running: 'Updating… this can take a few minutes; token counting is set up at the same time if it is missing. The page reloads when it is done.',
    update_failed: e => `Could not update: ${e}. You can also ask your AI agent: copy the sentence below.`,
    update_copy: 'Copy a request for your AI agent', update_copied: 'Copied. Paste it into Claude Code or whichever agent you use.',
    update_prompt: (latest, repo) => `Update agent-hud to v${latest}. Follow the "Updating" steps in https://github.com/${repo}#updating`,
    feedback_open: 'send feedback ↗',
  },
  ko: {
  wt_title: '같은 저장소를 받아 둔 다른 폴더 (worktree)',
  wt_intro: 'worktree는 같은 저장소를 다른 브랜치로 동시에 작업하려고 다른 폴더에 한 번 더 받아 둔 것입니다. 이 폴더에 넣은 스킬은 그쪽으로 저절로 따라가지 않습니다. 공유할 스킬만 고르면 되고, 플러그인·훅·에이전트·설정은 건드리지 않으며 기존 폴더와 링크는 그대로 둡니다.',
  wt_root_only: '스킬을 적용하려면 저장소의 worktree 루트를 선택하세요. 하위 폴더의 구성은 그 폴더에만 적용됩니다.',
  wt_query_failed: 'Git worktree 목록을 읽지 못했습니다.',
  wt_skills: '공유할 스킬', wt_targets: 'worktree 선택',
  wt_preview: '미리보기', wt_apply: '없는 스킬 추가',
  wt_auto_on: '저장하고 새 worktree에 자동 적용', wt_auto_off: '자동 적용 끄기',
  wt_auto_active: '자동 적용이 켜져 있습니다. 새 기본 구성을 저장하면 이후에 만든 worktree부터 적용됩니다.',
  wt_auto_inactive: '자동 적용이 꺼져 있습니다. 꺼도 기존 스킬은 유지됩니다.',
  wt_poll: n => `HUD 실행 중에는 ${n}초마다 새 worktree를 확인합니다. 첫 세션이 스킬 적용보다 먼저 시작될 수 있습니다.`,
  wt_session: '파일 상태를 표시합니다. 실행 중인 세션의 스킬 목록은 /skills에서 확인하세요. Codex는 변경을 감지하며, Claude는 세션 시작 때 없던 디렉터리라면 /reload-skills가 필요할 수 있습니다.',
  wt_claude: '.claude/skills를 만들면 최신 Claude Code가 원본 checkout에서 대신 읽던 스킬이 빠질 수 있습니다. Codex에만 공유하려면 .agents/skills만 선택하세요.',
  wt_confirm: '미리보기에 나온 경로에 없는 스킬만 추가할까요? 기존 파일·링크와 충돌 항목은 유지하고, 쓰기 전에 대상 상태를 다시 확인합니다.',
  wt_auto_confirm: '선택한 구성을 저장소의 새 worktree에 자동 적용할까요? 이미 있는 worktree는 바꾸지 않으며 스킬을 삭제하지 않습니다.',
  wt_override_confirm: '이 worktree의 자동 적용 방식을 저장할까요? 별도 구성은 위에서 선택한 스킬과 디렉터리를 사용합니다. 기존 스킬은 유지됩니다.',
  wt_inherit: '저장소 기본 구성', wt_exclude: '자동 적용 제외', wt_custom: '위 선택으로 별도 구성',
  wt_mode_inherit: '기본 구성', wt_mode_exclude: '제외', wt_mode_custom: '별도 구성',
  wt_saved: '저장했습니다', wt_unavailable: '사용 불가 또는 미확인', wt_detached: 'detached HEAD',
  wt_preview_needed: '스킬과 worktree를 선택하고 미리보기로 결과를 확인하세요.',
  wt_created: '추가됨', wt_linked: '연결됨', wt_original: '원본 폴더',
  wt_missing: '없음', wt_broken: '끊어진 링크', wt_conflict: '다른 원본',
  wt_occupied: '기존 파일·폴더', wt_blocked: '링크 또는 접근 불가 디렉터리',
  wt_source_missing: '원본 사용 불가', wt_choose: '스킬·디렉터리·worktree를 하나 이상 선택하세요.',
  wt_applied_at: at => `마지막 자동 적용: ${new Date(at*1000).toLocaleString()}`,
  wt_state_note: '아래 worktree 상태는 저장된 구성 기준입니다. 체크를 바꾸면 미리보기에만 반영됩니다.',
  wt_detail: '상세', wt_skill_col: '스킬', wt_source_detail: '원본 경로',
    banner: '항상 / 이름 칠 때만 / 제외 스위치는 에이전트를 <b>다음에 새로 열 때부터</b> 적용됩니다. 그룹 만들기와 프로젝트 등록은 바로 반영됩니다.',
    headline_title: '이 폴더에서 세션마다 처음에 읽히고, 메시지를 보낼 때마다 다시 함께 가는 양:',
    headline_none: '이 폴더에서 세션 시작 때 읽히는 것이 없습니다.',
    hl_instr: n => `지침 ${n}개`, hl_skills: n => `스킬 ${n}개`,
    hl_tok: n => `약 ${n.toLocaleString()}토큰`, hl_tok_na: '토큰 안 셈',
    title_groups: '그룹', title_instructions: '에이전트 지침', title_skills: '플러그인 & 스킬',
  guide_rows: [
    ['항상', '세션마다 AI가 이름과 설명을 읽습니다. 그때마다 토큰이 듭니다.'],
    ['/이름 칠 때만 사용', '/이름 을 치기 전까지 AI는 이 스킬을 모릅니다. 그 토큰이 절약됩니다. (.claude/settings.local.json → skillOverrides: "user-invocable-only". 스킬 파일의 disable-model-invocation: true와 같은 효과, 파일은 안 건드림)'],
    ['제외', '이 프로젝트에서 AI가 못 씁니다. (skillOverrides: "off")'],
  ],
  badge_on_tip: a => `${a}가 이 프로젝트에서 이 스킬을 쓸 수 있습니다`,
  badge_off_tip: a => `${a}는 이 프로젝트에서 이 스킬을 못 찾습니다. "다른 에이전트도 쓰게"를 누르면 생깁니다`,
  no_skills: '어느 폴더에서도 스킬을 못 찾았습니다.',
  link_failed: '스킬을 넣지 못했습니다: ',
  loose_skills: '플러그인 없이 설치한 스킬',
    set_apply: '이 프로젝트에 적용', set_applied: '이 프로젝트에 적용됨',
    assign_confirm: (g, p, pl, sk) => `"${g}"를 이 프로젝트에 적용할까요?\n${p}\n\n항상: ${pl}\n스킬 ${sk}개 연결\n그 밖의 플러그인과 스킬: 제외 (이 프로젝트에서만)`,
    unassign_confirm: (g, p) => `"${g}" 적용을 풀까요?\n${p}\n\n연결한 스킬을 지우고, 플러그인과 항상·제외 상태를 적용 전으로 되돌립니다. 적용 뒤 직접 바꾼 값은 그대로입니다.`,
    kind_plugin: '플러그인', kind_skill: '스킬',
    add_member_ph: '+ 플러그인 또는 스킬 추가…',
    member_plugin_tip: '이 프로젝트에서 항상',
    member_skill_tip: '이 프로젝트에 걸려 있음',
    assign_failed: '그룹을 적용하지 못했습니다: ',
    on: '항상', off: '제외', manual: '/이름 칠 때만 사용',
    remove: '빼기 ✕', remove_tip: (m,g) => `"${g}" 그룹에서 ${m} 빼기`,
    remove_confirm: (m,g) => `"${g}" 그룹에서 ${m} 뺄까요?`,
    groups_guide: '그룹은 함께 켜는 플러그인과 스킬의 묶음입니다. 프로젝트에서 그룹 하나를 고르면 그 안의 스위치가 한꺼번에 바뀌어, 하나씩 누르지 않아도 됩니다.',
    new_group: '+ 새 그룹 만들기', new_group_tip: '예: 개발용, 영상제작용',
    new_group_name_prompt: '새 그룹 이름 (예: "개발", "영상제작"):',
    new_group_first_prompt: '어떤 플러그인부터 넣을까요?\n',
    no_groups: '아직 그룹이 없습니다. 그룹은 함께 켜는 플러그인과 스킬의 묶음입니다. 예를 들어 개발용 하나, 영상제작용 하나.',
  not_found: '없음',
  claude_excluded: 'Claude Code에서 제외',
  claude_excluded_tip: '이 프로젝트에서 Claude Code는 이 파일을 읽지 않습니다 (claudeMdExcludes). 다른 에이전트와는 상관없습니다.',
  comp: {agents: '서브에이전트', mcp: 'MCP', commands: '커맨드', hooks: '훅', lsp: 'LSP',
    monitors: '모니터', bin: '실행파일', settings: '기본설정'},
  comp_count: (label, n) => `${label} ${n}개`,
  comp_tip: n => `이 플러그인에 같이 든 것: ${n}. 다른 에이전트에 보낼 수 있는 것은 스킬뿐입니다`,
  share_to: names => names.join('·') + '도 쓰게 하기',
  share_short: '다른 에이전트도 쓰게 만듦',
  help_tip: '어떻게 되는 건지',
  share_done: '모든 에이전트가 쓸 수 있음',
  share_all_tip: '체크하면 이 프로젝트 안에서 Codex·Cursor·Copilot·Gemini CLI·Antigravity가 스킬을 찾아보는 폴더(.agents/skills 등)에 이 스킬의 심볼릭 링크를 넣습니다. 복사본은 생기지 않고 원본은 그 자리에 있으며, 체크를 풀면 링크만 지웁니다. Claude Code는 플러그인이 켜져 있어야 읽습니다.',
  partly: a => `${a}는 이 플러그인의 스킬 중 일부만 쓸 수 있습니다`,
  add_project: '+ 폴더 추가', add_project_tip: '아무 폴더나 됩니다. git 저장소가 아니어도 됩니다',
  add_project_prompt: '추가할 폴더의 전체 경로:',
  add_project_failed: '폴더를 추가하지 못했습니다: ',
  no_project_yet: '아직 폴더가 없습니다',
  sidebar_search_ph: '폴더 검색…',
  sidebar_favorites: '즐겨찾기', sidebar_recent: '최근 사용', sidebar_all: '전체',
  sidebar_no_match: '검색 결과가 없습니다',
  pin_tip: '즐겨찾기에 추가', unpin_tip: '즐겨찾기에서 제거',
  forget_tip: '목록에서 빼기',
  forget_confirm: p => `이 폴더를 목록에서 뺄까요?\n\n${p}\n\n폴더와 그 안의 설정은 그대로 둡니다. 그 폴더에서 에이전트 세션을 열면 다시 나타납니다.`,
  install_app: '앱으로 설치',
  install_manual: '이 브라우저는 자동 설치가 안 됩니다.<br><b>Chrome·Edge:</b> 주소창의 설치 아이콘.<br><b>Safari(macOS 소노마 이상):</b> 파일 → Dock에 추가.',
  tok_head: (enc, total, n) => `스킬 이름과 설명이 세션마다 약 ${total.toLocaleString()}토큰을 차지합니다 (찾은 스킬 ${n}개, ${enc}로 셈)`,
  tok_head_part: (enc, total, m, n) => `찾은 스킬 ${n}개 중 ${m}개만 세어 약 ${total.toLocaleString()}토큰입니다 (${enc}로 셈). 나머지는 못 세서 실제 합계보다 적습니다`,
  tok_head_none: n => `스킬 ${n}개를 찾았지만 하나도 세지 못했습니다`,
  tok_unmeasured: n => `${n}개는 이름이나 설명이 없거나 파일을 읽지 못해 세지 않았습니다`,
  tok_off: n => `찾은 스킬 ${n}개 · 토큰 세기는 아직 준비되지 않았습니다`,
  tok_hint: {
    setup: '토큰 수 세기가 아직 준비되지 않았습니다. 터미널에서 한 번 실행하세요:',
    import: '토큰 수 세기 도구가 덜 설치됐습니다. setup을 다시 실행하세요:',
    cache: '토크나이저 어휘 파일이 아직 없습니다. setup을 실행하세요:',
    download: '토크나이저 어휘 파일을 받지 못했습니다. 네트워크를 확인하고 setup을 다시 실행하세요:',
    error: '이번에는 세지 못했고 곧 다시 시도합니다. 도구를 다시 설치하려면:'},
  tok_tip: '세션을 시작할 때 스킬 목록이 AI의 기억 공간을 얼마나 차지하는지 어림한 값입니다. 스킬마다 이름과 설명만 세고 본문은 세지 않으며, 이 컴퓨터에서 o200k_base 토크나이저로 셉니다. 청구액이나 제공자가 센 숫자는 아닙니다.',
  tok_skill: n => `${n.toLocaleString()}토큰`,
  tok_skill_na: '못 셈', tok_skill_na_tip: '이 스킬은 이름이나 설명이 없거나 파일을 읽지 못해 세지 않았습니다.',
  spec_issue: '형식 문제',
  issue: {
    unreadable: () => 'SKILL.md를 읽지 못했습니다',
    no_frontmatter: () => 'YAML frontmatter가 없습니다',
    frontmatter_unclosed: () => 'YAML frontmatter가 ---로 닫히지 않았습니다',
    name_missing: () => 'name이 없습니다',
    name_format: i => `name "${i.name}" — 소문자·숫자·하이픈 하나씩만, 64자 이내`,
    name_mismatch: i => `name "${i.name}", 폴더 이름 "${i.folder}" — 서로 다릅니다`,
    desc_missing: () => 'description이 없습니다',
    desc_long: i => `description이 ${i.len}자입니다 (상한 1024)`,
  },
  scan_truncated: '프로젝트가 커서 탐색을 중간에 멈췄습니다. 더 아래에 있는 지침 파일은 빠졌을 수 있습니다.',
  scope_global: '이 컴퓨터 전체 (모든 프로젝트)', scope_project: '이 프로젝트',
  agents_head: '서브에이전트',
    no_subagents: '서브에이전트 없음',
    loading: '불러오는 중…', error: '오류: ',
    toggle_failed: '켜고 끄지 못했습니다: ', group_update_failed: '그룹을 바꾸지 못했습니다: ',
    plugin_on_tip: '이 프로젝트에서는 세션을 시작할 때마다 AI가 이 플러그인의 스킬을 전부 읽습니다. 누르면 제외됩니다 (다음 세션부터)',
    plugin_off_tip: '이 프로젝트에서는 AI가 이 플러그인을 못 씁니다. 누르면 다시 켜집니다 (다음 세션부터)',
    skill_on_tip: '이 프로젝트에서는 세션을 시작할 때마다 AI가 이 스킬의 이름과 설명을 읽습니다. 누르면 /이름 칠 때만 읽게 됩니다 (다음 세션부터)',
    skill_off_tip: '이 프로젝트에서는 AI가 이 스킬을 못 씁니다. 누르면 다시 켜집니다 (다음 세션부터)',
    skill_manual_tip: '채팅에 /이름 을 치기 전까지 AI는 이 스킬이 있는 줄 모릅니다. 누르면 제외됩니다 (다음 세션부터)',
    skill_manual_md_tip: '이 스킬의 SKILL.md에 disable-model-invocation: true가 적혀 있어 모든 프로젝트에서 이렇게 동작합니다. 누르면 이 프로젝트에서 제외됩니다 (다음 세션부터). 자동으로 쓰게 하려면 그 파일을 고칩니다',
    skill_toggle_failed: '스킬을 켜고 끄지 못했습니다: ',
    skills_count: n => '스킬 ' + n + '개',
    group_tag: g => '그룹: ' + g,
    from: '출처: ',
    read_full_tip: '설명 전체 보기',
    no_skills_found: '스킬이 없습니다',
    updated: '갱신 ', every_n: n => `${n}초마다`, paused: '멈춤',
    usage: (mb, cpu) => `${mb}MB` + (cpu === null ? '' : ` · CPU ${cpu}%`),
    period_tip: '이 화면이 파일을 얼마나 자주 다시 읽을지',
    switching: '바꾸는 중…',
    update_available: (v, latest, repo) => `↑ 새 버전이 나왔습니다: v${latest} (지금은 v${v}) · <a href="https://github.com/${repo}/releases/latest" target="_blank" rel="noopener">바뀐 점</a>`,
    update_now: '지금 업데이트', update_running: '업데이트하는 중입니다. 토큰 세기가 아직 없으면 같이 준비하므로 몇 분 걸릴 수 있고, 끝나면 화면이 새로고침됩니다.',
    update_failed: e => `업데이트하지 못했습니다: ${e}. AI 에이전트에게 맡기려면 아래 문장을 복사해 붙여넣으세요.`,
    update_copy: 'AI에게 보낼 문장 복사', update_copied: '복사했습니다. Claude Code나 쓰는 AI 에이전트 창에 붙여넣으세요.',
    update_prompt: (latest, repo) => `agent-hud를 최신 버전(v${latest})으로 업데이트해줘. https://github.com/${repo}#updating 의 "Updating" 절차를 따라줘.`,
    feedback_open: '피드백 보내기 ↗',
  },
};
let lang = new URLSearchParams(location.search).get('lang') || localStorage.getItem('agent-hud-lang') || 'en';
function t(){ return T[lang]; }
function renderLangToggle(){
  document.documentElement.lang = lang;
  document.getElementById('langEn').classList.toggle('active', lang === 'en');
  document.getElementById('langKo').classList.toggle('active', lang === 'ko');
  document.getElementById('installBtn').textContent = t().install_app;
  closeInstallPop();
}
function setLang(l){
  lang = l;
  localStorage.setItem('agent-hud-lang', lang);
  renderLangToggle();
  document.getElementById('applyBanner').innerHTML = t().banner;
  renderHeadline();
  renderPeriod();
  renderTabs();
  tick();
}
document.getElementById('langEn').onclick = () => setLang('en');
document.getElementById('langKo').onclick = () => setLang('ko');
renderLangToggle();
document.getElementById('applyBanner').innerHTML = t().banner;
let lastTokens = null, lastLoad = null;
// 머리글: 에이전트마다 세션 시작 때 읽히는 지침·스킬 수와 토큰. 메시지마다 다시 보내지는 양이기도 하다.
// 읽는 것이 하나도 없는 에이전트는 줄을 빼고, 토큰을 못 셌으면 그 칸만 비운다.
function renderHeadline(){
  const el = document.getElementById('h1sub');
  const ld = lastLoad; if(!ld){ el.textContent = ''; return; }
  const rows = Object.entries(ld).filter(([, v]) => v.instructions + v.skills > 0);
  if(!rows.length){ el.textContent = t().headline_none; return; }
  el.innerHTML = `<div class="hl-title">${t().headline_title}</div>` + rows.map(([a, v]) =>
    `<div class="hl-row"><span class="hl-agent">${shortAgent(a)}</span><span>${t().hl_instr(v.instructions)}</span><span>${t().hl_skills(v.skills)}</span><span class="${v.tokens === null ? 'dim' : 'hl-tok'}">${v.tokens === null ? t().hl_tok_na : t().hl_tok(v.tokens)}</span></div>`).join('');
}

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
// Chrome/Edge만 이 이벤트를 준다 -- Safari는 "Dock에 추가"를 코드로 띄우는 API 자체가 없다.
// 버튼은 항상 보이고, 자동화가 되면(prompt 저장돼 있으면) 바로 설치 대화상자를 띄우고,
// 안 되면 드롭다운으로 수동 안내를 보여준다.
let deferredInstallPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferredInstallPrompt = e; });
window.addEventListener('appinstalled', () => { deferredInstallPrompt = null; closeInstallPop(); });
function closeInstallPop(){ document.getElementById('installPop').classList.remove('open'); }
document.getElementById('installBtn').onclick = async (e) => {
  e.stopPropagation();
  if(deferredInstallPrompt){
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    return;
  }
  const pop = document.getElementById('installPop');
  pop.innerHTML = t().install_manual;
  pop.classList.toggle('open');
};
document.addEventListener('click', (e) => { if(!e.target.closest('#installWrap')) closeInstallPop(); });
const shortAgent = a => a.replace(' CLI','');
// 스킬 한 줄의 토큰 뱃지. 숫자가 없는데 측정이 켜져 있으면 이름·설명을 못 읽은 스킬이다.
function tokTag(s, tk){
  if(!tk || tk.state !== 'ok') return null;
  const tag = document.createElement('span'); tag.className = 'tag'; tag.style.marginLeft = '8px';
  if(typeof s.tokens === 'number'){ tag.textContent = t().tok_skill(s.tokens); }
  else { tag.textContent = t().tok_skill_na; tag.title = t().tok_skill_na_tip; }
  return tag;
}
// 참고용 토큰 수 요약. 못 셌을 때는 0이나 어림값 대신 "측정 안 함"과 setup 명령을 보여준다.
function renderTokens(c, tk, agents){
  if(!tk) return;
  const box = document.createElement('div'); box.className = 'loadline'; box.title = t().tok_tip;
  const line = document.createElement('div'); box.appendChild(line);
  const note = txt => { const n = document.createElement('div'); n.className = 'note'; n.textContent = txt; box.appendChild(n); return n; };
  if(tk.state === 'ok'){
    // 전부 센 값만 "합계"라 부른다. 일부만 셌으면 센 것의 합이라고 밝히고, 하나도 못 셌으면 숫자를 내지 않는다.
    line.textContent = tk.measured === tk.skills ? t().tok_head(tk.encoding, tk.total, tk.skills)
      : tk.measured === 0 ? t().tok_head_none(tk.skills)
      : t().tok_head_part(tk.encoding, tk.total, tk.measured, tk.skills);
    if(tk.measured > 0 && tk.measured < tk.skills) note(t().tok_unmeasured(tk.skills - tk.measured));
  } else {
    box.className += ' loadline-off';
    line.textContent = t().tok_off(tk.skills);
    note((t().tok_hint[tk.state] || t().tok_hint.error));
    const cmd = document.createElement('code'); cmd.textContent = tk.setup; cmd.style.userSelect = 'all';
    box.appendChild(cmd);
  }
  c.appendChild(box);
}
const fmtTime = ts => new Date(ts*1000).toLocaleDateString(undefined,{month:'2-digit',day:'2-digit'}) + ' ' + new Date(ts*1000).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'});
const TITLE_MAP = { Groups: 'title_groups', 'Instructions & agents (read-only)': 'title_instructions', 'Skills (who can see them)': 'title_skills' };
const TABS = ['Skills (who can see them)', 'Instructions & agents (read-only)', 'Groups'];
// ?tab= 이 있으면 그걸 쓴다. 특정 탭을 링크로 걸거나 캡처할 때 필요하다.
let activeTab = new URLSearchParams(location.search).get('tab') || localStorage.getItem('agent-hud-tab') || TABS[0];
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
const worktreeDrafts = {};
const worktreeRowOpen = {};
let worktreeOpen = false;
// 사이드바 상태: 지금 프로젝트 선택(agent-hud-project)과 같은 자리(localStorage)에 둔다.
// 서버 쪽 파일을 늘리지 않아도 되고, 기기별로 다른 즐겨찾기를 갖는 게 오히려 자연스럽다.
function readJSON(key, fallback){ try{ return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch(e){ return fallback; } }
let favorites = readJSON('agent-hud-favorites', []);
let recents = readJSON('agent-hud-recents', {});
function saveFavorites(){ localStorage.setItem('agent-hud-favorites', JSON.stringify(favorites)); }
function toggleFavorite(path){
  favorites = favorites.includes(path) ? favorites.filter(p => p !== path) : [...favorites, path];
  saveFavorites(); renderSidebar(lastPanels);
}
async function forgetProject(path){
  if(!confirm(t().forget_confirm(path))) return;
  try{ await fetch('/api/unregister', {method:'POST', body: JSON.stringify({path})}); }
  catch(e){ alert(t().error + e); return; }
  favorites = favorites.filter(p => p !== path); saveFavorites();
  delete recents[path]; localStorage.setItem('agent-hud-recents', JSON.stringify(recents));
  if(selectedProject === path){ selectedProject = ''; localStorage.removeItem('agent-hud-project'); }
  await tick();
}
function chooseProject(path){
  selectedProject = path; localStorage.setItem('agent-hud-project', path);
  recents[path] = Date.now();
  // 화면엔 최근 5개만 보이므로(renderSidebarList) 저장도 5개로 자른다 -- 안 그러면
  // 연 적 있는 프로젝트 전부가 지워지지 않고 계속 쌓인다.
  recents = Object.fromEntries(Object.entries(recents).sort((a, b) => b[1] - a[1]).slice(0, 5));
  localStorage.setItem('agent-hud-recents', JSON.stringify(recents));
  rerender();
}
function baseName(p){ return (p||'').split('/').filter(Boolean).pop() || p; }
function parentName(p){ const parts = (p||'').split('/').filter(Boolean); return parts.length > 1 ? parts[parts.length - 2] : ''; }
let sidebarQuery = '';
let lastPanels = null;
// 프로젝트 선택기. 사이드바 하나가 모든 탭을 대표한다 -- 예전엔 탭마다 드롭다운을 복제해 갖고 있었다.
// 검색창(input)은 언어가 안 바뀌는 한 한 번만 만들고 다시는 지우지 않는다.
// 예전엔 keystroke마다, 그리고 1초 폴링 tick마다 사이드바 전체(input 포함)를 지우고 새로 만들었는데,
// 그러면 한글 입력 중 조합 상태를 쥔 DOM 노드가 통째로 사라져서 조합이 깨졌다(agy로도 같은 진단 확인).
// 목록(.sb-list)만 다시 그리고, input 노드 자체는 절대 건드리지 않는다.
let sidebarShellLang = null;
function renderSidebar(p){
  lastPanels = p;
  const side = document.getElementById('sidebar');
  if(sidebarShellLang !== lang){
    side.innerHTML = '';
    const search = document.createElement('div'); search.className = 'sb-search';
    search.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>';
    const input = document.createElement('input');
    input.id = 'sbSearchInput';
    input.placeholder = t().sidebar_search_ph; input.value = sidebarQuery;
    input.oninput = () => { sidebarQuery = input.value; renderSidebarList(); };
    search.appendChild(input);
    side.appendChild(search);
    const listWrap = document.createElement('div'); listWrap.className = 'sb-list';
    side.appendChild(listWrap);
    sidebarShellLang = lang;
  }
  renderSidebarList();
}
function renderSidebarList(){
  const p = lastPanels;
  const listWrap = document.getElementById('sidebar').querySelector('.sb-list');
  listWrap.innerHTML = '';
  const list = (p && p.known_projects) || [];
  const q = sidebarQuery.trim().toLowerCase();
  const matches = pr => !q || pr.toLowerCase().includes(q);
  // 이름이 같은 폴더가 둘 이상이면(예: 여러 워크스페이스의 build/) 상위 폴더명을 옆에 붙인다.
  const nameCounts = {};
  for(const pr of list) nameCounts[baseName(pr)] = (nameCounts[baseName(pr)] || 0) + 1;

  function group(labelKey, paths){
    const shown = paths.filter(matches);
    if(!shown.length) return;
    const g = document.createElement('div'); g.className = 'sb-group';
    const label = document.createElement('div'); label.className = 'sb-label'; label.textContent = t()[labelKey];
    g.appendChild(label);
    for(const path of shown){
      const it = document.createElement('div');
      it.className = 'sb-item' + (path === p.project_dir ? ' active' : '') + (favorites.includes(path) ? ' pinned' : '');
      it.title = path;
      const dot = document.createElement('span'); dot.className = 'sb-dot' + (path === p.project_dir ? '' : ' idle');
      const name = document.createElement('span'); name.className = 'sb-name'; name.textContent = baseName(path);
      it.appendChild(dot); it.appendChild(name);
      if(nameCounts[baseName(path)] > 1){
        const parent = document.createElement('span'); parent.className = 'sb-parent'; parent.textContent = parentName(path);
        it.appendChild(parent);
      }
      const pin = document.createElement('button'); pin.className = 'sb-pin';
      pin.title = favorites.includes(path) ? t().unpin_tip : t().pin_tip;
      pin.innerHTML = favorites.includes(path)
        ? '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.6 6.6L21 9.3l-5 4.6L17.3 21 12 17.6 6.7 21 8 13.9l-5-4.6 6.4-.7L12 2z"/></svg>'
        : '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l2.6 6.6L21 9.3l-5 4.6L17.3 21 12 17.6 6.7 21 8 13.9l-5-4.6 6.4-.7L12 2z"/></svg>';
      pin.onclick = (e) => { e.stopPropagation(); toggleFavorite(path); };
      it.appendChild(pin);
      const rm = document.createElement('button'); rm.className = 'sb-pin sb-rm';
      rm.title = t().forget_tip; rm.textContent = '×';
      rm.onclick = (e) => { e.stopPropagation(); forgetProject(path); };
      it.appendChild(rm);
      it.onclick = () => chooseProject(path);
      g.appendChild(it);
    }
    listWrap.appendChild(g);
  }

  const pinned = list.filter(pr => favorites.includes(pr));
  const recent = list.filter(pr => !favorites.includes(pr) && recents[pr])
    .sort((a, b) => (recents[b]||0) - (recents[a]||0)).slice(0, 5);
  const rest = list.filter(pr => !favorites.includes(pr) && !recent.includes(pr));

  group('sidebar_favorites', pinned);
  group('sidebar_recent', recent);
  group('sidebar_all', rest);

  if(!list.length){
    const empty = document.createElement('div'); empty.className = 'sb-empty'; empty.textContent = t().no_project_yet;
    listWrap.appendChild(empty);
  } else if(q && !pinned.some(matches) && !recent.some(matches) && !rest.some(matches)){
    const empty = document.createElement('div'); empty.className = 'sb-empty'; empty.textContent = t().sidebar_no_match;
    listWrap.appendChild(empty);
  }

  const add = document.createElement('div'); add.className = 'sb-add'; add.textContent = t().add_project;
  add.title = t().add_project_tip;
  add.onclick = async () => {
    polling = false;
    let path = '';
    try{
      const p = await (await fetch('/api/pick-folder', {method:'POST'})).json();
      path = p.ok ? p.path : (prompt(t().add_project_prompt) || '').trim();
    } catch(e){ path = (prompt(t().add_project_prompt) || '').trim(); }
    if(!path){ polling = true; return; }
    try{
      const r = await fetch('/api/register', {method:'POST', body: JSON.stringify({path})});
      const d = await r.json();
      if(!d.ok){ alert(t().add_project_failed + (d.error || t().error)); }
      else chooseProject(path);
    } catch(e){ alert(t().add_project_failed + e); }
    polling = true;
    await tick();
  };
  listWrap.appendChild(add);
}
// ?open=<플러그인> 으로 펼친 채 열 수 있다 (?tab= 과 같은 이유)
const helpOpen = {};
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
// off가 먼저다. 머리말이 수동 전용이어도 off면 목록과 / 메뉴 어디에도 나오지 않는다(공식 문서).
function skillSwitch(s){
  const st = s.override === 'off' ? 'off' : s.manual_only || s.override === 'user-invocable-only' ? 'manual' : s.enabled ? 'on' : 'off';
  return { st, next: { on: 'user-invocable-only', manual: 'off', off: 'on' }[st] };
}

async function toggleSkill(name, value, el){
  polling = false; el.classList.add('busy');
  try{
    const r = await fetch('/api/skilltoggle', {method:'POST', body: JSON.stringify({name, value, project: currentProjectDir})});
    const d = await r.json();
    if(!d.ok) alert(t().skill_toggle_failed + (d.error || t().error));
  } catch(e){ alert(t().skill_toggle_failed + e); }
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
// 피드백은 GitHub Issues로 받는다. 코딩 에이전트를 쓰는 사람이 대상이라 GitHub 계정이
// 걸림돌이 될 가능성이 낮고, 별도 수신 서버를 두는 것보다 이슈 폼 하나가 낫다. 버전은 링크가 미리 채워 보낸다.
function renderFeedback(upd){
  const a = document.getElementById('fbLink');
  a.textContent = t().feedback_open;
  a.href = `https://github.com/${upd.repo}/issues/new?template=feedback.yml&version=${encodeURIComponent(upd.version)}`;
}
// 업데이트 알림. Homebrew 설치본은 버튼 하나로 끝낸다(brew가 파일을 바꾸고 서버가 새 코드로 다시 뜬다).
// git 설치본은 코드를 고쳐 쓰고 있을 수 있어 에이전트에게 맡길 문장을 복사해 준다.
// 배너는 tick마다 다시 그려지므로 버튼 상태는 updState에 둔다.
let updState = '';  // '' | 'running' | 'copied' | 'failed'
let updError = '';
function renderUpdate(upd){
  const el = document.getElementById('updateBanner');
  if(!(upd && upd.has_update)){ el.style.display = 'none'; return; }
  el.innerHTML = t().update_available(upd.version, upd.latest, upd.repo) + ' ';
  const prompt = t().update_prompt(upd.latest, upd.repo);
  const copyBtn = () => {
    const b = document.createElement('button'); b.className = 'btn'; b.textContent = t().update_copy;
    b.onclick = async () => {
      try{ await navigator.clipboard.writeText(prompt); updState = updState === 'failed' ? 'failed' : 'copied'; }
      catch(e){ window.prompt('', prompt); }
      renderUpdate(upd);
    };
    return b;
  };
  if(updState !== 'running'){
    if(upd.brew && updState !== 'failed'){
      const b = document.createElement('button'); b.className = 'btn'; b.textContent = t().update_now;
      b.onclick = () => runUpdate(upd);
      el.append(b);
    } else {
      el.append(copyBtn());
    }
  }
  const msg = updState === 'running' ? t().update_running
    : updState === 'copied' ? t().update_copied
    : updState === 'failed' ? t().update_failed(updError) : '';
  if(msg){ const m = document.createElement('div'); m.style.marginTop = '6px'; m.textContent = msg; el.append(m); }
  if(updState === 'failed'){ const q = document.createElement('code'); q.textContent = prompt; el.append(q); }
  el.style.display = '';
}
async function runUpdate(upd){
  updState = 'running'; renderUpdate(upd);
  try{
    const r = await fetch('/api/update', {method: 'POST', body: '{}'});
    const d = await r.json();
    if(d.ok){
      // 서버가 새 코드로 다시 뜨는 동안에는 응답이 없다. 다시 응답하면 새로고침한다.
      await new Promise(r => setTimeout(r, 2000));
      for(let i = 0; i < 60; i++){
        try{ if((await fetch('/manifest.json')).ok) break; } catch(e){}
        await new Promise(r => setTimeout(r, 1000));
      }
      location.reload(); return;
    }
    updState = 'failed'; updError = d.error || 'unknown error';
  } catch(e){ updState = 'failed'; updError = String(e); }
  renderUpdate(upd);
}
function wtState(state){ return t()['wt_' + state] || state; }
const WT_WARN = ['conflict', 'broken', 'occupied', 'blocked', 'source_missing'];
// 폴더별 상태 개수: ".agents/skills: 연결됨 2, 없음 1 · .claude/skills: ..."
function wtSummary(skills){
  const by = {};
  for(const s of skills){ const d = by[s.dir] ||= {}; d[s.state] = (d[s.state] || 0) + 1; }
  return Object.entries(by).map(([dir, c]) =>
    dir + ': ' + Object.entries(c).map(([st, n]) => wtState(st) + ' ' + n).join(', ')).join(' · ');
}
// 스킬 한 행, 대상 폴더별 상태 열. 펼침 여부는 프로젝트+워크트리별로 폴링 재렌더 뒤에도 유지한다.
function wtDetail(row, project){
  const key = project + '\n' + row.path;
  const d = document.createElement('details'); d.className = 'wt-detail';
  d.open = !!worktreeRowOpen[key]; d.ontoggle = () => { worktreeRowOpen[key] = d.open; };
  const s = document.createElement('summary'); s.textContent = t().wt_detail; d.appendChild(s);
  const dirs = [...new Set(row.skills.map(x=>x.dir))];
  const table = document.createElement('table'); table.style.cssText = 'border-collapse:collapse;margin:4px 0';
  const tr = (cells, head) => {
    const r = document.createElement('tr');
    for(const c of cells){
      const td = document.createElement(head ? 'th' : 'td'); td.textContent = c; td.style.cssText = 'padding:2px 10px 2px 0';
      if(head){ td.scope = 'col'; td.style.textAlign = 'left'; }
      r.appendChild(td);
    }
    table.appendChild(r);
  };
  tr([t().wt_skill_col, ...dirs], true);
  for(const name of [...new Set(row.skills.map(x=>x.name))]){
    tr([name, ...dirs.map(dir => { const x = row.skills.find(k=>k.name === name && k.dir === dir); return x ? wtState(x.state) : '-'; })]);
  }
  d.appendChild(table);
  return d;
}
async function worktreeRequest(action, project, extra){
  const response = await fetch('/api/worktrees', {method: 'POST',
    body: JSON.stringify({action, project, ...extra})});
  return response.json();
}
function renderWorktrees(container, w, project){
  if(!w) return;
  const wrap = document.createElement('details'); wrap.style.cssText = 'margin:12px 0;padding:12px;border:1px solid var(--border);border-radius:8px';
  wrap.open = worktreeOpen;
  wrap.ontoggle = () => { worktreeOpen = wrap.open; };
  const summary = document.createElement('summary'); summary.textContent = t().wt_title;
  summary.style.cursor = 'pointer'; wrap.appendChild(summary);
  const note = (text) => { const n = document.createElement('div'); n.className = 'note'; n.textContent = text; wrap.appendChild(n); return n; };
  note(t().wt_intro);
  note(w.enabled ? t().wt_auto_active : t().wt_auto_inactive);
  note(t().wt_poll(w.poll_seconds));
  note(t().wt_session);
  note(t().wt_claude);
  if(w.query_failed){ note(t().wt_query_failed); container.appendChild(wrap); return; }
  if(!w.can_apply) note(t().wt_root_only);
  const draft = worktreeDrafts[project] ||= {
    skills: w.config ? w.config.skills.map(s=>({...s})) : w.skills.filter(s=>s.selected).map(s=>({name:s.name,source:s.source})),
    dirs: w.config ? [...w.config.dirs] : ['.agents/skills', '.claude/skills'], targets: [], preview: null, srcOpen: {}
  };
  const config = () => ({skills: draft.skills, dirs: draft.dirs});
  const invalidate = () => { draft.preview = null; output.textContent = t().wt_preview_needed; apply.disabled = true; };
  const skillTitle = document.createElement('div'); skillTitle.textContent = t().wt_skills; skillTitle.style.marginTop = '12px'; wrap.appendChild(skillTitle);
  const skills = document.createElement('div'); skills.style.cssText = 'max-height:170px;overflow:auto;margin:6px 0';
  // Include pinned defaults whose installation is no longer in the source index.
  const choices = [...w.skills];
  for(const selected of draft.skills){
    if(!choices.some(s=>s.name === selected.name && s.source === selected.source)) choices.push(selected);
  }
  // One row per name. Same names from different sources stay a single explicit choice via the select.
  const sourcesByName = new Map();
  for(const sk of choices){
    if(!sourcesByName.has(sk.name)) sourcesByName.set(sk.name, []);
    sourcesByName.get(sk.name).push(sk.source);
  }
  for(const [name, sources] of sourcesByName){
    const item = document.createElement('div'); item.className = 'wt-skill'; item.dataset.name = name; item.style.cssText = 'font-size:12px;padding:2px 0';
    const pinned = draft.skills.find(s=>s.name === name);
    let source = pinned ? pinned.source : sources[0];
    const label = document.createElement('label');
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.disabled = !w.can_apply; cb.checked = !!pinned;
    cb.onchange = () => {
      draft.skills = draft.skills.filter(s=>s.name !== name);
      if(cb.checked) draft.skills.push({name,source});
      invalidate();
    };
    label.appendChild(cb); label.appendChild(document.createTextNode(' ' + name)); item.appendChild(label);
    if(sources.length > 1){
      const pick = document.createElement('select'); pick.style.cssText = 'margin-left:8px;max-width:60%'; pick.disabled = !w.can_apply;
      for(const s of sources){ const op = document.createElement('option'); op.value = s; op.textContent = s; pick.appendChild(op); }
      pick.value = source;
      pick.onchange = () => {
        source = pick.value;
        if(cb.checked){ draft.skills = draft.skills.map(s=>s.name === name ? {name,source} : s); invalidate(); }
      };
      item.appendChild(pick);
    }
    const more = document.createElement('details'); more.style.cssText = 'margin-left:20px';
    more.open = !!draft.srcOpen[name]; more.ontoggle = () => { draft.srcOpen[name] = more.open; };
    const ms = document.createElement('summary'); ms.textContent = t().wt_source_detail; more.appendChild(ms);
    for(const s of sources){ const p = document.createElement('div'); p.className = 'dim'; p.textContent = s; more.appendChild(p); }
    item.appendChild(more); skills.appendChild(item);
  }
  wrap.appendChild(skills);
  for(const dir of ['.agents/skills','.claude/skills']){
    const label = document.createElement('label'); label.style.marginRight = '12px';
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = draft.dirs.includes(dir); cb.disabled = !w.can_apply;
    cb.onchange = () => { draft.dirs = draft.dirs.filter(d=>d !== dir); if(cb.checked) draft.dirs.push(dir); invalidate(); };
    label.appendChild(cb); label.appendChild(document.createTextNode(' '+dir)); wrap.appendChild(label);
  }
  note(t().wt_targets);
  note(t().wt_state_note);
  for(const row of w.rows){
    const line = document.createElement('div'); line.className = 'wt-row'; line.style.cssText = 'padding:8px 0;border-top:1px solid var(--border);font-size:12px;overflow-wrap:anywhere';
    const label = document.createElement('label'); const cb = document.createElement('input'); cb.type = 'checkbox';
    cb.disabled = !w.can_apply || !row.available; cb.checked = draft.targets.includes(row.path);
    cb.onchange = () => { draft.targets = draft.targets.filter(p=>p !== row.path); if(cb.checked) draft.targets.push(row.path); invalidate(); };
    label.appendChild(cb); label.appendChild(document.createTextNode(' '+row.path+' · '+(row.branch || t().wt_detached)));
    line.appendChild(label);
    const mode = document.createElement('select'); mode.style.marginLeft = '8px'; mode.disabled = !w.can_apply || !row.available;
    for(const value of ['inherit','exclude','custom']){
      const op = document.createElement('option'); op.value=value; op.textContent=t()['wt_'+value]; mode.appendChild(op);
    }
    mode.value = row.mode;
    mode.onchange = async () => {
      const selected = mode.value;
      if(!confirm(t().wt_override_confirm)){ mode.value = row.mode; return; }
      try{
        const r = await worktreeRequest('override', project, {target:row.path,mode:selected,config:config()});
        if(!r.ok) alert(r.error || t().error);
        await rerender();
      } catch(e){ alert(t().error+e); mode.value=row.mode; }
    };
    line.appendChild(mode);
    const state = document.createElement('div'); state.className = 'dim';
    state.textContent = row.available ? t()['wt_mode_'+row.mode] : t().wt_unavailable;
    if(row.skills.length) state.textContent += ' · '+wtSummary(row.skills);
    if(row.result){ state.textContent += ' · '+t().wt_applied_at(row.result.at); if(row.result.error) state.textContent += ' · '+row.result.error; }
    line.appendChild(state);
    // Children are appended after the text is final: a later textContent write would wipe them.
    const warns = row.skills.filter(s=>WT_WARN.includes(s.state));
    if(warns.length){
      const warn = document.createElement('div'); warn.className = 'wt-warn'; warn.style.color = 'var(--danger, #e5534b)';
      warn.textContent = warns.map(s=>s.name+' ('+s.dir+'): '+wtState(s.state)).join(', ');
      line.appendChild(warn);
    }
    if(row.skills.length) line.appendChild(wtDetail(row, project));
    wrap.appendChild(line);
  }
  const actions = document.createElement('div'); actions.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;margin:8px 0'; wrap.appendChild(actions);
  const button = text => { const b = document.createElement('button'); b.textContent=text; b.className='card-action'; actions.appendChild(b); return b; };
  const preview = button(t().wt_preview); preview.disabled = !w.can_apply;
  const apply = button(t().wt_apply); apply.disabled = !w.can_apply || !draft.preview;
  const save = button(t().wt_auto_on); save.disabled = !w.can_apply;
  const off = button(t().wt_auto_off); off.disabled = !w.can_apply || !w.enabled;
  const output = document.createElement('pre'); output.style.cssText = 'white-space:pre-wrap;font:12px/1.5 inherit;overflow-wrap:anywhere'; wrap.appendChild(output);
  function showResult(result){
    const lines = (result.rows||[]).map(r=>r.project+'/'+r.dir+'/'+r.name+' → '+r.source+' · '+wtState(r.state));
    if(result.error) lines.unshift(result.error);
    output.textContent = lines.join('\n') || t().wt_saved;
  }
  if(draft.preview) showResult(draft.preview); else output.textContent = t().wt_preview_needed;
  preview.onclick = async () => {
    try{
      if(!draft.skills.length || !draft.dirs.length || !draft.targets.length){ alert(t().wt_choose); return; }
      draft.preview = await worktreeRequest('preview', project, {targets:draft.targets,config:config()});
      showResult(draft.preview); apply.disabled = !draft.preview.ok;
    } catch(e){ invalidate(); alert(t().error+e); }
  };
  apply.onclick = async () => {
    if(!draft.preview || !confirm(t().wt_confirm)) return;
    apply.disabled = true;
    try{
      draft.preview = await worktreeRequest('apply', project, {targets:draft.targets,config:config()});
      showResult(draft.preview);
    } catch(e){ invalidate(); alert(t().error+e); }
  };
  save.onclick = async () => {
    if(!confirm(t().wt_auto_confirm)) return;
    try{
      const r = await worktreeRequest('policy', project, {enabled:true,config:config()});
      if(!r.ok) alert(r.error || t().error); else await rerender();
    } catch(e){ alert(t().error+e); }
  };
  off.onclick = async () => {
    try{
      const r = await worktreeRequest('policy', project, {enabled:false});
      if(!r.ok) alert(r.error || t().error); else await rerender();
    } catch(e){ alert(t().error+e); }
  };
  container.appendChild(wrap);
}

async function tick(){
  if(!polling) return;
  const r = await fetch(stateUrl()); const d = await r.json();
  const upd = d.panels.find(p => p.panel === 'update');
  renderUpdate(upd);
  const sp = d.panels.find(p => p.tokens) || {};
  lastTokens = sp.tokens || null; lastLoad = sp.load || null;
  renderHeadline();
  if(upd) renderFeedback(upd);
  renderSidebar(d.panels.find(p => p.known_projects) || {known_projects: [], project_dir: selectedProject});
  const app = document.getElementById('app');
  // 탭 안의 드롭다운이나 입력 칸을 쓰는 중이면 이번 갱신은 건너뛴다. 다시 그리면 그 요소가
  // 새것으로 바뀌어, 펼쳐 둔 "플러그인 또는 스킬 추가" 목록이 몇 초 만에 닫힌다.
  const busy = document.activeElement;
  if(busy && app.contains(busy) && ['SELECT', 'INPUT', 'TEXTAREA'].includes(busy.tagName)) return;
  app.innerHTML='';
  for(const p of d.panels){
    if(p.project_dir) currentProjectDir = p.project_dir;
    if(p.title !== activeTab) continue;
    const c = document.createElement('div'); c.className='card wide';
    // 패널 제목은 탭이 이미 보여 주므로 본문에는 다시 쓰지 않는다.
    if(p.title === 'Groups'){
      const gd = document.createElement('div'); gd.className = 'guide'; gd.textContent = t().groups_guide; c.appendChild(gd);
      const headerRow = document.createElement('div'); headerRow.style.cssText='display:flex;align-items:center;justify-content:flex-end;margin-bottom:6px';
      const newBtn = document.createElement('span'); newBtn.className='card-action';
      newBtn.textContent = t().new_group;
      newBtn.title = t().new_group_tip;
      newBtn.onclick = () => {
        const name = prompt(t().new_group_name_prompt);
        if(!name) return;
        const first = prompt(t().new_group_first_prompt + (p.all_plugins||[]).join('\n'));
        if(first) editGroup('add', name.trim(), first.trim(), 'plugin');
      };
      headerRow.appendChild(newBtn);
      c.appendChild(headerRow);
      if(!p.groups.length){
        const e = document.createElement('div'); e.className = 'empty';
        e.innerHTML = `<span>🗂</span><span>${t().no_groups}</span>`;
        c.appendChild(e);
      }
      for(const g of p.groups){
        const wrap = document.createElement('div'); wrap.className = 'section';
        const el = document.createElement('div'); el.className='row sec-head';

        const left = document.createElement('span'); left.className = 'sec-left';
        const gname = document.createElement('span'); gname.style.fontWeight='600';
        gname.textContent = g.name;
        left.appendChild(gname);
        const plugins = g.members.filter(m => m.kind === 'plugin');
        const skills = g.members.filter(m => m.kind === 'skill');

        const right = document.createElement('span'); right.className = 'sec-right';
        const apply = document.createElement('span');
        apply.className = 'btn' + (g.assigned ? ' btn-on' : '');
        apply.textContent = g.assigned ? t().set_applied : t().set_apply;
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
          addSel.blur();  // 포커스가 남아 있으면 render가 갱신을 건너뛰어, 추가한 줄이 안 보인다
          editGroup('add', g.name, rest.join(':'), kind);
        };
        addRow.appendChild(addSel);
        wrap.appendChild(addRow);
        c.appendChild(wrap);
      }

    } else if(p.files){
      // 같은 내용을 읽는 파일은 원본 아래에 들여 쓴다. 들여쓰기가 "이 파일은 저 파일을 읽는다"를
      // 말하므로 문장 뱃지는 없고, 파일 안에 실제로 적힌 `@경로`나 링크 화살표만 그대로 보여 준다.
      const byPath = new Map(p.files.map(f => [f.path, f]));
      const targetsOf = f => !f.link ? [] : f.link.kind === 'symlink' ? [f.link.target] : f.link.targets.map(x => x.path);
      const children = new Map();
      for(const f of p.files) for(const tp of targetsOf(f)) if(byPath.has(tp)) (children.get(tp) || children.set(tp, []).get(tp)).push(f);
      const nested = new Set([...children.values()].flat().map(f => f.path));
      const base = q => q.split('/').pop();
      const home = q => q.replace(/^\/Users\/[^/]+|^\/home\/[^/]+/, '~');
      const drawFile = (f, depth) => {
        const el = document.createElement('div'); el.className = 'row' + (f.exists ? ' clickable' : '');
        el.style.paddingLeft = (depth * 22) + 'px';
        const left = document.createElement('span');
        const caret = document.createElement('span');
        caret.textContent = f.exists ? '▸ ' : '';
        left.appendChild(caret);
        left.insertAdjacentHTML('beforeend', `${depth ? '<span class="dim">↳ </span>' : ''}<span class="dot ${f.exists && !(f.claude_excluded && (!f.tool || f.tool === 'Claude Code'))?'on':'off'}" style="cursor:default"></span>${home(f.name)}${f.tool ? `<span class="tooltag">${f.tool}</span>` : ''}${f.claude_excluded ? `<span class="tooltag" title="${t().claude_excluded_tip}">${t().claude_excluded}</span>` : ''}`);
        // 파일에 적힌 연결을 글자 그대로: 링크는 → 대상, 가져오기는 @대상. 대상이 없으면 흐리게 지운다.
        if(f.link){
          const refs = f.link.kind === 'symlink' ? [{text: '→ ' + base(f.link.target), ok: f.link.ok, path: f.link.target}]
                                                   : f.link.targets.map(x => ({text: '@' + base(x.path), ok: x.ok, path: x.path}));
          for(const r of refs) left.insertAdjacentHTML('beforeend', ` <span class="dim mono" title="${home(r.path)}"${r.ok ? '' : ' style="text-decoration:line-through"'}>${r.text}</span>`);
        }
        const sizeSpan = document.createElement('span'); sizeSpan.className = 'dim';
        sizeSpan.textContent = f.exists ? f.size + 'B · ' + fmtTime(f.mtime) : t().not_found;
        el.appendChild(left); el.appendChild(sizeSpan);
        c.appendChild(el);
        const box = document.createElement('div'); box.className = 'content';
        if(f.exists){ el.onclick = () => showContent(f.path, box, caret); }
        c.appendChild(box);
        if(depth < 4) for(const ch of children.get(f.path) || []) drawFile(ch, depth + 1);
      };
      for(const [scope, label] of [['global', t().scope_global], ['project', t().scope_project]]){
        const top = p.files.filter(f => f.scope === scope && !nested.has(f.path));
        if(!top.length) continue;
        const sh = document.createElement('div'); sh.className = 'row sec-head'; sh.innerHTML = `<b>${label}</b>`;
        c.appendChild(sh);
        for(const f of top) drawFile(f, 0);
      }
      if(p.truncated){
        const w = document.createElement('div'); w.className = 'note';
        w.style.color = 'var(--text)';
        w.textContent = '⚠ ' + t().scan_truncated;
        c.appendChild(w);
      }
      const ah = document.createElement('div'); ah.className = 'row sec-head';
      ah.innerHTML = `<b>${t().agents_head}</b><span class="dim mono">.claude/agents/</span><span class="tooltag">Claude Code</span><span class="tooltag">Cursor</span><span class="tooltag">Copilot</span>`;
      c.appendChild(ah);
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
    } else {
      // 위계: 상태 한 줄(토큰) → 스위치 뜻 세 줄(흐리게) → 본문 목록 → worktree(접힘, 맨 아래)
      renderTokens(c, p.tokens, p.agents);
      if(p.agents){
        // 스위치 세 단계가 무엇을 하는지. 처음 보는 사람이 라벨만 보고는 알 수 없어서 목록 위에 둔다.
        const g = document.createElement('div'); g.className = 'guide';
        g.innerHTML = t().guide_rows.map(([k, v]) => `<div class="guide-row"><b>${k}</b><span>${v}</span></div>`).join('');
        c.appendChild(g);
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
          gtag.className = 'tag clickable'; gtag.textContent = t().group_tag(g);
          gtag.onclick = e => { e.stopPropagation(); activeTab = 'Groups'; localStorage.setItem('agent-hud-tab', activeTab); renderTabs(); rerender(); };
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
          tag.title = t().comp_tip(label);
          badges.appendChild(tag);
        }
        const st = row.section_state || {};
        // 플러그인 밖 스킬은 출처도 대상도 제각각이라 한 줄로 요약할 수 없다.
        // 꺼진(no) 에이전트는 뱃지로 안 그린다 -- 누가 보는지만 보여주고, 빠진 곳은
        // 아래 체크박스 툴팁으로 옮긴다. 줄마다 뱃지 6개가 늘어서던 것을 줄인다.
        for(const a of (isPlugin ? (p.agents||[]) : [])){
          const v = st[a] || 'none';
          if(v === 'none') continue;
          const tag = document.createElement('span');
          tag.className = 'agenttag ' + (v === 'all' ? 'yes' : 'partial');
          tag.textContent = shortAgent(a);
          tag.title = v === 'some' ? t().partly(a) : t().badge_on_tip(a);
          badges.appendChild(tag);
        }
        meta.appendChild(badges);
        const secMiss = (p.agents||[]).filter(a => (st[a] || 'none') !== 'all');
        const ids = (row.skills||[]).filter(x => x.linkable).map(x => x.id);
        const helpBoxes = [];
        if(ids.length && isPlugin){
          const share = document.createElement('label');
          share.className = 'share' + (secMiss.length ? '' : ' share-done');
          const cb = document.createElement('input'); cb.type = 'checkbox';
          cb.checked = (row.skills||[]).every(x => x.shared);
          cb.onclick = e => { e.stopPropagation(); linkSkill(ids, cb.checked, share); };
          share.appendChild(cb);
          share.appendChild(document.createTextNode(secMiss.length ? t().share_short : t().share_done));
          share.title = secMiss.length ? t().share_to(secMiss.map(shortAgent)) : '';
          meta.appendChild(share);
          // (?) 를 누르면 기술 설명이 그 줄 아래에 펼쳐진다. 늘 보일 필요는 없는 글이라 평소엔 숨긴다.
          const help = document.createElement('span'); help.className = 'help'; help.textContent = '?';
          help.title = t().help_tip;
          const helpBox = document.createElement('div'); helpBox.className = 'note help-box';
          helpBox.style.display = helpOpen[key] ? '' : 'none';   // 몇 초마다 다시 그려도 펼친 채로 남게
          helpBox.textContent = t().share_all_tip;
          help.onclick = e => { e.stopPropagation(); helpOpen[key] = !helpOpen[key]; helpBox.style.display = helpOpen[key] ? '' : 'none'; };
          meta.appendChild(help);
          helpBoxes.push(helpBox);
        }
        wrap.appendChild(meta);
        for(const hb of helpBoxes) wrap.appendChild(hb);

        if(skillsOpen[key]){
          if(hasSkills){
            for(const s of row.skills){
              const srow = document.createElement('div'); srow.className = 'row sub skill-row';
              if(!isPlugin && s.enabled !== undefined){
                // 플러그인 밖 스킬만 스위치가 있다. 플러그인 스킬은 플러그인째 켜고 끈다.
                const ssw = document.createElement('span');
                // 켜짐 → 수동 → 꺼짐 → 켜짐. name-only 는 쓰는 사람이 드물어 스위치에 안 넣었다.
                const {st, next} = skillSwitch(s);
                ssw.className = 'switch sw-' + st;
                ssw.textContent = t()[st];
                ssw.title = s.manual_only && st === 'manual' ? t().skill_manual_md_tip : { on: t().skill_on_tip, manual: t().skill_manual_tip, off: t().skill_off_tip }[st];
                ssw.onclick = e => { e.stopPropagation(); toggleSkill(s.name, next, ssw); };
                srow.appendChild(ssw);
              }

              const stext = document.createElement('div'); stext.className = 'skill-text';
              const sname = document.createElement('div'); sname.className = 'skill-name';
              sname.textContent = s.name;
              const ttag = tokTag(s, p.tokens);
              if(ttag) sname.appendChild(ttag);
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
              // 다르면 켜진 것과 꺼진 것을 다 그린다. 여기서 꺼진 것을 빼면 "아무 데서도
              // 안 보이는 스킬"이 뱃지 0개가 되어 "섹션과 같음"과 화면에서 구별되지 않는다.
              const badges = document.createElement('span');
              const secUniform = isPlugin && (p.agents||[]).every(a => (row.section_state||{})[a] !== 'some');
              const sec = (p.agents||[]).filter(a => (row.section_state||{})[a] === 'all').join('|');
              if(!secUniform || (s.agents||[]).join('|') !== sec){
                for(const a of (p.agents||[])){
                  // 스위치로 끈 스킬은 Claude Code가 읽지 않는다. 폴더를 볼 수 있어도 꺼진 것으로 그린다.
                  const on = (s.agents||[]).includes(a) && !(a === 'Claude Code' && s.enabled === false);
                  const tag = document.createElement('span');
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
                  share.appendChild(document.createTextNode(miss.length ? t().share_short : t().share_done));
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
      renderWorktrees(c, p.worktrees, p.project_dir);
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


def _png_chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def _solid_png(size, rgb):
    # "앱으로 설치" 버튼의 매니페스트 아이콘. PNG 하나로 충분해서 이미지 라이브러리를
    # 넣지 않고 손으로 인코딩한다 -- 필터 바이트 0(그대로) + zlib. 픽셀 단위로 그린다.
    return _raster_png(size, lambda x, y: rgb)


def _raster_png(size, pixel):
    """pixel(x, y) -> (r,g,b) 함수를 픽셀마다 불러 PNG로 인코딩한다."""
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # 필터 없음
        for x in range(size):
            rows.extend(pixel(x, y))
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8bit, RGB
    idat = zlib.compress(bytes(rows), 9)
    return sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def _loadline_icon(size, bg, ring, fill):
    """흘수선 마크: 원 하나를 수평선이 관통하고, 선 아래가 fill로 채워진다.
    이미지 라이브러리 없이 원의 방정식만으로 그린다(스킬 로드 도구가 그림 라이브러리를
    끌어들일 이유가 없다)."""
    cx = cy = size / 2
    radius = size * 0.24
    ring_w = max(1, size * 0.052)
    line_half = size * 0.345

    def pixel(x, y):
        dx, dy = x + 0.5 - cx, y + 0.5 - cy
        r = (dx * dx + dy * dy) ** 0.5
        on_ring = abs(r - radius) <= ring_w / 2
        on_line = abs(dy) <= ring_w / 2 and abs(dx) <= line_half
        if on_ring or on_line:
            return ring
        if r < radius and dy > ring_w / 2:
            return fill
        return bg

    return _raster_png(size, pixel)


ICON_PNG = _loadline_icon(512, bg=(20, 21, 15), ring=(236, 238, 228), fill=(232, 187, 78))
MANIFEST_JSON = json.dumps({
    "name": "Agent HUD", "short_name": "Agent HUD", "start_url": "/",
    "display": "standalone", "background_color": "#14150f", "theme_color": "#1c1e17",
    "icons": [{"src": "/icon.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}],
}).encode()


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
        elif self.path == "/manifest.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json")
            self.send_header("Content-Length", str(len(MANIFEST_JSON)))
            self.end_headers()
            self.wfile.write(MANIFEST_JSON)
        elif self.path == "/icon.png":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(ICON_PNG)))
            self.end_headers()
            self.wfile.write(ICON_PNG)
        else:
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        if self.path == "/api/worktrees":
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("bad request")
            except (ValueError, TypeError):
                return self._send_json({"ok": False, "error": "bad request"}, 400)
            project = payload.get("project")
            repo = git_repository(project)
            # A discovered checkout is usable if its repository is already known.
            # Merely looking at it never registers it or edits its settings.
            known = [git_repository(p) for p in known_projects()]
            if not repo or not any(r and r["common_dir"] == repo["common_dir"] for r in known):
                return self._send_json({"ok": False, "error": "unknown repository"}, 400)
            action = payload.get("action")
            config = payload.get("config")
            if action == "preview":
                result = preview_worktree_skills(project, payload.get("targets"), config)
            elif action == "apply":
                result = apply_worktree_skills(project, payload.get("targets"), config)
            elif action == "policy" and isinstance(payload.get("enabled"), bool):
                result = set_worktree_policy(project, config, payload["enabled"])
            elif action == "override":
                result = set_worktree_override(project, payload.get("target"), payload.get("mode"), config)
            else:
                return self._send_json({"ok": False, "error": "unknown action"}, 400)
            return self._send_json(result)
        elif self.path == "/api/toggle":
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
        elif self.path == "/api/skilltoggle":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send_json({"ok": False, "error": "bad request"}, 400)
            project = payload.get("project", "") or PROJECT_DIR
            if project not in known_projects():
                return self._send_json({"ok": False, "error": "unknown project"}, 400)
            value = payload.get("value") if "value" in payload else bool(payload.get("enable"))
            ok, err = set_skill_overrides({payload.get("name", ""): value}, project)
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
        elif self.path == "/api/pick-folder":
            path = pick_folder()
            self._send_json({"ok": path is not None, "path": path or ""})
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
        elif self.path == "/api/unregister":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send_json({"ok": False, "error": "bad request"}, 400)
            unregister_project(payload.get("path", ""))
            self._send_json({"ok": True})
        elif self.path == "/api/update":
            prefix = brew_prefix()
            if not prefix:
                return self._send_json({"ok": False, "error": "not a Homebrew install"}, 400)
            ok, err = brew_update(prefix, read_json(UPDATE_CACHE_FILE).get("latest"))
            self._send_json({"ok": ok, "error": err})
            if ok:
                threading.Thread(target=restart_into, args=(prefix,), daemon=True).start()
        else:
            self._send_json({"ok": False, "error": "not found"}, 404)


# 127.0.0.1로 가는 요청이 환경 변수의 프록시로 새지 않게 한다.
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def hud_alive(port):
    """그 포트에서 응답하는 게 Agent HUD인지 본다. 다른 프로그램이 그 포트를 쓰는데 열려 있다는
    것만 보고 '이미 떠 있다'고 끝내면, 대시보드가 영영 뜨지 않는다."""
    try:
        with LOCAL.open(f"http://127.0.0.1:{port}/manifest.json", timeout=1) as r:
            return json.loads(r.read()).get("name") == "Agent HUD"
    except Exception:
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


SETUP_VENV_SECONDS = 120
SETUP_PIP_SECONDS = 600


def _step(label, cmd, timeout):
    print(f"{label}...", flush=True)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        why = f"no answer after {timeout}s" if isinstance(e, subprocess.TimeoutExpired) else str(e)
        print(f"agent-hud: tokenizer setup failed at: {label} ({why})", file=sys.stderr)
        return False
    if p.returncode != 0:
        tail = (p.stderr or p.stdout).strip().splitlines()[-5:]
        print("agent-hud: tokenizer setup failed at: " + label, file=sys.stderr)
        print("\n".join(tail), file=sys.stderr)
        return False
    return True


def _venv_version():
    """tokenizer venv의 파이썬 (주, 부) 버전. 못 알아내면 None."""
    py = _tokenizer_python()
    if not py:
        return None
    try:
        p = subprocess.run([py, "-I", "-c", "import sys; print(*sys.version_info[:2])"],
                           capture_output=True, text=True, timeout=30)
        major, minor = p.stdout.split()
        return int(major), int(minor)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def cli_tokens(args):
    if args != ["setup"]:
        print(USAGE, file=sys.stderr)
        return 2
    print(f"Tokenizer setup with {sys.executable} (Python {sys.version.split()[0]})")
    print(f"  venv:  {TOKENIZER_VENV}\n  cache: {TOKENIZER_CACHE}")
    os.makedirs(TOKENIZER_CACHE, exist_ok=True)
    is_venv = os.path.isfile(os.path.join(TOKENIZER_VENV, "pyvenv.cfg"))
    if os.path.lexists(TOKENIZER_VENV) and not is_venv and (not os.path.isdir(TOKENIZER_VENV) or os.listdir(TOKENIZER_VENV)):
        # --clear 로 지우는 것은 venv 표시(pyvenv.cfg)가 있는 이 폴더뿐이다. 그 밖의 것은 건드리지 않는다.
        print(f"agent-hud: {TOKENIZER_VENV} exists but is not a tokenizer venv. Move or remove it, then run setup again.",
              file=sys.stderr)
        return 1
    # 다른 파이썬으로 다시 돌렸으면(예: 3.15용 완성품이 없어 python3.13으로) venv도 그 파이썬으로 다시 만든다
    if not (is_venv and _venv_version() == tuple(sys.version_info[:2])):
        if not _step("Recreating the venv for this Python" if is_venv else "Creating the venv",
                     [sys.executable, "-m", "venv"] + (["--clear"] if is_venv else []) + [TOKENIZER_VENV],
                     SETUP_VENV_SECONDS):
            return 1
    # --only-binary: 이 파이썬용 완성품이 없으면 컴파일을 시작하지 말고 바로 알려준다
    if not _step("Installing " + TOKENIZER_REQUIREMENT,
                 [_tokenizer_python() or os.path.join(TOKENIZER_VENV, "bin", "python"), "-m", "pip", "install",
                  "--disable-pip-version-check", "--quiet", "--only-binary=:all:", TOKENIZER_REQUIREMENT],
                 SETUP_PIP_SECONDS):
        print("If no prebuilt tiktoken exists for this Python, run setup with an older python3.x "
              "(for example python3.13).", file=sys.stderr)
        return 1
    print(f"Downloading the {TOKEN_ENCODING} vocabulary (one time, public file)...", flush=True)
    out, err = _run_tokenizer("warm", timeout=300)
    if out is None:
        print(f"agent-hud: tokenizer setup failed ({err}). Check your network and run it again.", file=sys.stderr)
        return 1
    out, err = _run_tokenizer("count", ["hello world"])
    if out is None or out.get("counts") != [2]:
        print(f"agent-hud: tokenizer check failed ({err or 'unexpected result'}).", file=sys.stderr)
        return 1
    print(f'Ready: {TOKEN_ENCODING}, "hello world" = 2 tokens. Counting runs offline from now on.')
    return 0


def cli_worktrees(args):
    """An optional pre-launch command, sharing the dashboard's additive writer."""
    apply = bool(args and args[0] == "apply")
    rest = args[1:] if apply else args
    project = os.path.abspath(rest[0] if rest else os.getcwd())
    repo = git_repository(project)
    if not repo or project != repo["root"]:
        print("저장소의 worktree 루트 폴더를 선택하세요.", file=sys.stderr)
        return 1
    if not apply:
        print(json.dumps(collect_worktrees(project), ensure_ascii=False, indent=2))
        return 0
    policy = read_json(WORKTREE_FILE).get("repos", {}).get(repo["common_dir"], {})
    override = policy.get("overrides", {}).get(project, {})
    if override.get("mode") == "exclude":
        print("이 worktree는 자동 적용에서 제외돼 있습니다.", file=sys.stderr)
        return 1
    config = override.get("config", policy.get("config"))
    if not config:
        print("저장된 스킬 구성이 없습니다. 대시보드에서 먼저 선택하세요.", file=sys.stderr)
        return 1
    with _worktree_transaction():
        data = read_json(WORKTREE_FILE)
        result = _apply_worktree_skills(project, [project], config, data, trusted=True)
        write_json(WORKTREE_FILE, data, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


USAGE = """agent-hud                      대시보드를 띄웁니다
agent-hud open                 대시보드를 브라우저로 엽니다 (꺼져 있으면 띄운 뒤 엽니다)
agent-hud groups               그룹 목록
agent-hud apply <그룹> [폴더]   그룹을 폴더에 적용 (기본: 현재 폴더)
agent-hud apply --off [폴더]    적용 해제
agent-hud worktrees [폴더]      같은 저장소의 worktree와 스킬 파일 상태
agent-hud worktrees apply [폴더] 저장된 스킬 구성 추가 (세션 시작 전 선택 사항)
agent-hud tokens setup         스킬 토큰 수를 세는 도구(tiktoken)를 이 도구 폴더 안에 설치
agent-hud --version            버전 출력"""


def main():
    if sys.argv[1:2] in (["--version"], ["-V"]):
        print(f"agent-hud {VERSION}")
        sys.exit(0)
    if os.environ.get("CLAUDE_HUD_DISABLE") == "1":
        return
    global PROJECT_DIR
    argv = sys.argv[1:]
    if argv and argv[0] in ("groups", "apply", "worktrees", "tokens", "-h", "--help", "help"):
        if argv[0] in ("-h", "--help", "help"):
            print(USAGE)
            sys.exit(0)
        if argv[0] == "groups":
            sys.exit(cli_groups())
        if argv[0] == "worktrees":
            sys.exit(cli_worktrees(argv[1:]))
        if argv[0] == "tokens":
            sys.exit(cli_tokens(argv[1:]))
        rest = argv[1:]
        if not rest:
            print(USAGE, file=sys.stderr)
            sys.exit(1)
        group = "" if rest[0] == "--off" else rest[0]
        target = rest[1] if len(rest) > 1 else os.getcwd()
        sys.exit(cli_apply(group, target))
    # 모르는 인자로 서버를 띄우면 확인용 명령이 끝나지 않는다
    if argv and argv[0] != "open" and not (argv[0] == "--register" and len(argv) > 1):
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    if len(sys.argv) > 2 and sys.argv[1] == "--register":
        PROJECT_DIR = os.path.abspath(sys.argv[2])
    registering = len(sys.argv) > 2 and sys.argv[1] == "--register"
    opening = bool(argv) and argv[0] == "open"
    port = PORT
    url = f"http://127.0.0.1:{port}"

    def hand_off():
        # 이미 떠 있는 대시보드에 넘긴다. `open`이면 탭만 열고, 아니면(세션 훅, 서비스) 이 폴더만
        # 알려준다. 서비스가 부를 때 탭을 열면 launchd가 되살릴 때마다 탭이 쌓이므로 `open`에서만 연다.
        if opening:
            webbrowser.open(url, new=0, autoraise=True)
            return
        try:
            req = urllib.request.Request(
                f"{url}/api/register",
                data=json.dumps({"path": PROJECT_DIR}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            LOCAL.open(req, timeout=2)
        except Exception:
            pass

    if hud_alive(port):
        return hand_off()

    if opening:
        # 꺼져 있으면 서버를 따로 띄우고, 응답할 때까지 기다렸다가 연다. 이 명령이 직접 서버가 되면
        # 터미널이나 에이전트의 셸을 붙잡고 끝나지 않고, 그 셸이 닫힐 때 대시보드도 같이 죽는다.
        start_in_background()
        for _ in range(40):
            if hud_alive(port):
                webbrowser.open(url, new=0, autoraise=True)
                return
            time.sleep(0.25)
        print(f"agent-hud: the dashboard did not start. Is another program using port {port}?", file=sys.stderr)
        sys.exit(1)

    register_project(PROJECT_DIR)
    cleanup_known_projects()
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    # 다른 프로그램이 이 포트를 쓰고 있으면 옆 번호로 가지 않는다(위 PORT 설명).
    warned = False
    while True:
        try:
            httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            if hud_alive(port):
                return hand_off()  # 다른 Agent HUD가 한발 먼저 떴다
            if registering:
                return  # 세션 훅은 기다리지 않는다. 기다리면 세션을 열 때마다 프로세스가 하나씩 쌓인다
            if not warned:
                print(f"agent-hud: port {port} is used by another program. Waiting for it to be free.",
                      file=sys.stderr, flush=True)
                warned = True
            time.sleep(30)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    threading.Thread(target=_update_check_loop, daemon=True).start()
    threading.Thread(target=_worktree_apply_loop, daemon=True).start()
    if not os.environ.pop("AGENT_HUD_NO_BROWSER", None):
        webbrowser.open(url, new=0, autoraise=opening)
    # keep process alive in background; parent hook detaches us
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
