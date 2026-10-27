"""_loaded_count()가 실제로 로드되는 스킬만 세는지 본다.
   꺼진 플러그인의 스킬은 컨텍스트에 안 올라가므로 세지 않는다.
   permissions.deny로 차단한 스킬은 목록에 그대로 남는다(2026-09 센티널 실측, ADR 10).
   그래서 차단은 로드 수를 줄이지 않는다.
   스킬 이름+설명의 참고용 토큰 수(o200k_base)는 진짜 tiktoken으로 센다. 그 환경은
   AGENT_HUD_TEST_TOKENIZER_HOME (그 아래 tokenizer-venv, tokenizer-cache) 에 `tokens setup`으로 만들어 둔다.
   없으면 그 부분만 건너뛰고, CI에서는 없으면 실패한다.
   python3 tests/test_loaded.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)

C = ["Claude Code"]
OTHERS = ["Codex", "Cursor"]


def sk(name, agents=C, blocked=False):
    return {"id": name, "agents": agents, "blocked": blocked}


def unit():
    rows = [
        {"name": "on@m", "enabled": True, "skills": [sk("a"), sk("b"), sk("c", blocked=True)]},
        {"name": "off@m", "enabled": False, "skills": [sk("d"), sk("e")]},
        # 플러그인 밖의 스킬: Claude Code가 보는 것만 센다
        {"name": "", "enabled": None, "skills": [sk("f"), sk("g", agents=OTHERS)]},
    ]
    got = hud._loaded_count(rows)
    assert got == 4, f"켜진 플러그인 3(차단 포함) + 단독 1 = 4여야 하는데 {got}"

    # 플러그인을 끄면 그만큼 준다
    rows[0]["enabled"] = False
    assert hud._loaded_count(rows) == 1, "꺼진 플러그인의 스킬을 세고 있다"

    # 다른 에이전트만 보는 스킬은 Claude Code 컨텍스트에 안 올라간다
    rows[0]["enabled"] = True
    rows[2]["skills"][0]["agents"] = OTHERS
    assert hud._loaded_count(rows) == 3, "Claude Code가 못 보는 스킬을 세고 있다"

    assert hud._loaded_count([]) == 0


def end_to_end():
    """화면에 나가는 값 그대로: 차단한 플러그인 스킬도 Claude Code 뱃지를 유지하고 로드 수에 들어간다."""
    tmp = tempfile.mkdtemp()
    try:
        home = os.path.join(tmp, "home"); claude = os.path.join(home, ".claude")
        plugin = os.path.join(tmp, "plugin")
        for s in ("s1", "s2"):
            os.makedirs(os.path.join(plugin, "skills", s))
            with open(os.path.join(plugin, "skills", s, "SKILL.md"), "w") as f:
                f.write(f"---\nname: {s}\ndescription: test skill {s}\n---\nbody\n")
        os.makedirs(os.path.join(claude, "plugins"))
        json.dump({"plugins": {"p@m": [{"installPath": plugin, "version": "1"}]}},
                  open(os.path.join(claude, "plugins", "installed_plugins.json"), "w"))
        proj = os.path.join(tmp, "proj"); os.makedirs(os.path.join(proj, ".claude"))
        json.dump({"enabledPlugins": {"p@m": True}, "permissions": {"deny": ["Skill(p@m:s1)"]}},
                  open(os.path.join(proj, ".claude", "settings.local.json"), "w"))

        hud.HOME, hud.CLAUDE_DIR = home, claude
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        hud.SETS_FILE = os.path.join(tmp, "project-sets.json")
        hud.PROJECTS_FILE = os.path.join(tmp, "projects.json")

        state = hud.collect_skills({"project_dir": proj})
        row = next(r for r in state["rows"] if r["name"] == "p@m")
        s1 = next(s for s in row["skills"] if s["id"] == "s1")
        assert "Claude Code" in s1["agents"], "차단했다고 Claude Code가 못 보는 것처럼 표시한다"
        assert state["loaded"] == 2, f"차단한 스킬도 로드되므로 2여야 하는데 {state['loaded']}"
    finally:
        shutil.rmtree(tmp)


# ── 참고용 토큰 수 ─────────────────────────────────────────────────────────────
# 기대값은 구현과 따로 순수 tiktoken(o200k_base)에 "이름\n설명"을 넣어 얻은 숫자다.
LONG_DESC = " ".join(["hello world"] * 750)      # 8999자: 예전 read(8000)을 넘는다
TOK_HOME = os.environ.get("AGENT_HUD_TEST_TOKENIZER_HOME")


def write_skill(root, folder, desc="x", name=None, body="body", raw=None):
    d = os.path.join(root, folder); os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(raw if raw is not None else f"---\nname: {name or folder}\ndescription: {desc}\n---\n{body}\n")
    return d


def use_tokenizer(venv, cache):
    hud.TOKENIZER_VENV, hud.TOKENIZER_CACHE = venv, cache
    hud._token_counts.clear(); hud._token_failed = (0.0, "")


def real_tokenizer():
    if TOK_HOME:
        use_tokenizer(os.path.join(TOK_HOME, "tokenizer-venv"), os.path.join(TOK_HOME, "tokenizer-cache"))
        return True
    assert not os.environ.get("CI"), "CI에서는 AGENT_HUD_TEST_TOKENIZER_HOME 이 있어야 한다"
    return False


def world(tmp):
    """플러그인 2개(켜짐·꺼짐), 꺼진 쪽 스킬은 프로젝트 .agents/skills에 링크, 단독 스킬 여럿."""
    home = os.path.join(tmp, "home"); claude = os.path.join(home, ".claude")
    on, off = os.path.join(tmp, "on"), os.path.join(tmp, "off")
    write_skill(os.path.join(on, "skills"), "alpha", "hello world")
    write_skill(os.path.join(on, "skills"), "big", "hello world")
    write_skill(os.path.join(on, "skills"), "keep", "uses the body", body="lorem ipsum " * 5000)
    beta = write_skill(os.path.join(off, "skills"), "beta", "한국어 설명입니다")
    os.makedirs(os.path.join(claude, "plugins"))
    json.dump({"plugins": {"p@m": [{"installPath": on, "version": "1"}],
                           "off@m": [{"installPath": off, "version": "1"}]}},
              open(os.path.join(claude, "plugins", "installed_plugins.json"), "w"))
    proj = os.path.join(tmp, "proj"); os.makedirs(os.path.join(proj, ".claude"))
    json.dump({"enabledPlugins": {"p@m": True, "off@m": False}, "skillOverrides": {"offloose": "off"}},
              open(os.path.join(proj, ".claude", "settings.local.json"), "w"))
    os.makedirs(os.path.join(proj, ".agents", "skills"))
    os.symlink(beta, os.path.join(proj, ".agents", "skills", "beta"))
    agents, cl = os.path.join(home, ".agents", "skills"), os.path.join(home, ".claude", "skills")
    write_skill(agents, "gamma", "<|endoftext|>")
    write_skill(agents, "dup", "hello world"); write_skill(cl, "dup", "hello world")   # 두 폴더, 같은 스킬
    write_skill(cl, "offloose", "hello world")
    write_skill(cl, "nofm", raw="no frontmatter here\n")
    hud.HOME, hud.CLAUDE_DIR = home, claude
    hud.MODES_FILE = os.path.join(tmp, "modes.json")
    hud.SETS_FILE = os.path.join(tmp, "project-sets.json")
    hud.PROJECTS_FILE = os.path.join(tmp, "projects.json")
    return {"project_dir": proj}, on


def skill_of(state, sid):
    return next(s for r in state["rows"] for s in r["skills"] if s["id"] == sid)


def tokens_inventory(tmp):
    ctx, on = world(tmp)
    state = hud.collect_skills(ctx)
    tk = state["tokens"]
    assert tk["state"] == "ok" and tk["encoding"] == "o200k_base", tk
    want = {"alpha": 4, "big": 4, "keep": 5, "beta": 6, "gamma": 9, "dup": 4, "offloose": 6}
    assert {k: skill_of(state, k)["tokens"] for k in want} == want
    # 본문은 세지 않는다 (keep의 본문은 6만 자): 위 5가 이름+설명 값 그대로다
    assert skill_of(state, "nofm")["tokens"] is None, "머리말 없는 스킬에 폴더 이름으로 숫자를 붙였다"
    # 폴더 두 곳에 있는 dup, 링크로만 다른 에이전트에 보이는 꺼진 플러그인의 beta도 한 번만
    assert (tk["skills"], tk["measured"], tk["total"]) == (8, 7, 38), tk
    got = {a: (v["skills"], v["measured"], v["tokens"]) for a, v in tk["agents"].items()}
    # (볼 수 있는 스킬, 그중 센 스킬, 센 것의 합). 머리말 없는 nofm은 Claude Code·Cursor·Copilot이 볼 수 있지만 세지 못한다.
    # Claude Code: 꺼진 플러그인(beta)과 스위치로 끈 offloose는 빠진다. 나머지 에이전트는 그대로 본다.
    assert got == {"Claude Code": (5, 4, 17), "Codex": (3, 3, 19), "Cursor": (5, 4, 25), "Copilot": (5, 4, 25),
                   "Gemini CLI": (3, 3, 19), "Antigravity": (1, 1, 6)}, got
    # 뱃지와 합계가 같은 숫자를 쓴다: 겹치지 않는 스킬 값의 합이 전체 합이다
    assert sum(s["tokens"] or 0 for r in state["rows"] for s in r["skills"]) == tk["total"]
    assert state["loaded"] == 5, "옛 loaded 값(호환): 켜진 플러그인 3 + dup + nofm"
    if os.geteuid() != 0:                         # 읽을 수 없는 스킬도 찾은 수에는 들고 숫자는 없다
        md = os.path.join(hud.HOME, ".agents", "skills", "unread", "SKILL.md")
        write_skill(os.path.join(hud.HOME, ".agents", "skills"), "unread"); os.chmod(md, 0)
        state = hud.collect_skills(ctx)
        assert skill_of(state, "unread")["tokens"] is None
        assert (state["tokens"]["skills"], state["tokens"]["measured"]) == (9, 7)
        codex = state["tokens"]["agents"]["Codex"]
        assert (codex["skills"], codex["measured"], codex["tokens"]) == (4, 3, 19), codex   # 못 읽은 것도 볼 수 있는 스킬이다


def tokens_follow_real_lengths(tmp):
    """설명이 길어지면 같은 스킬의 수가 따라 늘고, 8000자를 넘는 설명도 끝까지 센다."""
    ctx, on = world(tmp)
    assert skill_of(hud.collect_skills(ctx), "big")["tokens"] == 4
    write_skill(os.path.join(on, "skills"), "big", LONG_DESC)
    state = hud.collect_skills(ctx)
    assert skill_of(state, "big")["tokens"] == 1502, skill_of(state, "big")["tokens"]
    assert state["tokens"]["total"] == 38 - 4 + 1502


def tokens_same_file_once(tmp):
    """같은 SKILL.md를 두 플러그인 항목이 가리켜도 한 번만 센다."""
    ctx, on = world(tmp)
    path = os.path.join(hud.CLAUDE_DIR, "plugins", "installed_plugins.json")
    data = json.load(open(path)); data["plugins"]["twin@m"] = [{"installPath": on, "version": "1"}]
    json.dump(data, open(path, "w"))
    tk = hud.collect_skills(ctx)["tokens"]
    assert (tk["skills"], tk["total"]) == (8, 38), tk


def tokens_count_once_per_poll(tmp):
    """화면이 2초마다 부르므로, 바뀐 게 없으면 토크나이저 프로세스를 다시 띄우지 않는다."""
    ctx, on = world(tmp)
    hud.collect_skills(ctx)
    calls = []; real = hud.subprocess.run
    py = os.path.join(hud.TOKENIZER_VENV, "bin", "python")     # git 등 다른 호출은 세지 않는다
    hud.subprocess.run = lambda *a, **k: (calls.append(a) if a[0][0] == py else None) or real(*a, **k)
    try:
        hud.collect_skills(ctx)
        assert not calls, "그대로인데 또 프로세스를 띄웠다"
        write_skill(os.path.join(on, "skills"), "alpha", "hello world again")
        hud.collect_skills(ctx)
        assert len(calls) == 1, f"바뀐 스킬 하나에 프로세스 {len(calls)}번"
    finally:
        hud.subprocess.run = real


def tokens_known_values():
    st, counts = hud.count_tokens(["hello world", "<|endoftext|>"])
    assert st == "ok" and counts["hello world"] == 2, (st, counts)
    assert counts["<|endoftext|>"] > 1, "특수 토큰 글자를 보통 글자로 세야 한다"
    # 캐시는 상한이 있다. 한 번에 상한보다 많이 물어도 답은 모두 나오고 저장은 상한까지만 한다.
    hud.TOKEN_CACHE_MAX = 2
    try:
        st, many = hud.count_tokens(["hello world", "a", "b", "c", "d"])
        assert st == "ok" and many["hello world"] == 2 and set(many) == {"hello world", "a", "b", "c", "d"}, (st, many)
        assert len(hud._token_counts) <= 2, len(hud._token_counts)
    finally:
        hud.TOKEN_CACHE_MAX = 4096


def tokens_not_measured(tmp):
    """토크나이저가 없거나 어휘를 안 받았으면 0이나 어림값 대신 '측정 안 함'과 setup 명령."""
    ctx, _ = world(tmp)
    use_tokenizer(os.path.join(tmp, "no-venv"), os.path.join(tmp, "no-cache"))
    state = hud.collect_skills(ctx)
    tk = state["tokens"]
    assert tk["state"] == "setup" and "tokens setup" in tk["setup"], tk
    assert tk["total"] is None and all(v["tokens"] is None for v in tk["agents"].values()), tk
    assert all(s["tokens"] is None for r in state["rows"] for s in r["skills"])
    assert tk["skills"] == 8, "찾은 스킬 수는 측정과 상관없이 보여준다"
    assert {a: (v["skills"], v["measured"]) for a, v in tk["agents"].items()} == {
        "Claude Code": (5, 0), "Codex": (3, 0), "Cursor": (5, 0), "Copilot": (5, 0), "Gemini CLI": (3, 0), "Antigravity": (1, 0)}, tk["agents"]
    # 설치가 덜 된 venv(tiktoken 없음)도 같은 취급이다. 파이썬 오류 문장이 화면으로 가지 않는다.
    import venv
    venv.create(os.path.join(tmp, "bare-venv"), with_pip=False)
    use_tokenizer(os.path.join(tmp, "bare-venv"), os.path.join(tmp, "no-cache"))
    tk = hud.collect_skills(ctx)["tokens"]
    assert tk["state"] == "import" and tk["total"] is None and "Traceback" not in json.dumps(tk), tk
    # 데이터 폴더를 옮겨 쓰는 설치(AGENT_HUD_HOME)면 명령에도 그 폴더가 들어가야 같은 곳에 설치된다
    os.environ["AGENT_HUD_HOME"] = hud.TOOL_DIR = "/some where/hud"
    try:
        assert hud.token_setup_command().startswith("AGENT_HUD_HOME='/some where/hud' python3 "), hud.token_setup_command()
    finally:
        del os.environ["AGENT_HUD_HOME"]; hud.TOOL_DIR = ROOT
    if TOK_HOME:                                  # venv는 있는데 어휘 캐시가 비어 있다: 몰래 받지 않는다
        empty = os.path.join(tmp, "empty-cache"); os.makedirs(empty)
        use_tokenizer(os.path.join(TOK_HOME, "tokenizer-venv"), empty)
        tk = hud.collect_skills(ctx)["tokens"]
        assert tk["state"] == "cache" and tk["total"] is None, tk
        assert os.listdir(empty) == [], "세는 중에 어휘를 내려받았다"


def tokens_frontmatter_edges(tmp):
    """머리말 경계는 줄 단위다: 설명 안의 `---` 글자는 경계가 아니고, 닫히지 않은(또는 읽기 상한에서 잘린) 머리말은 못 읽은 것이다."""
    ctx, on = world(tmp)
    skills = os.path.join(on, "skills")
    write_skill(skills, "demo", "hello --- world")                                   # 기대값: 순수 tiktoken "demo\nhello --- world" = 5
    write_skill(skills, "unclosed", raw="---\nname: unclosed\ndescription: hello world\n")
    write_skill(skills, "unclosed-body", raw="---\nname: unclosed-body\ndescription: hello\nbody --- more\n")
    write_skill(skills, "dashes", raw="----\nname: dashes\ndescription: hello world\n----\n")
    write_skill(skills, "dashes-open", raw="----\nname: dashes-open\ndescription: hello world\n---\n")
    write_skill(skills, "crlf", raw="---\r\nname: crlf\r\ndescription: hello world\r\n---\r\nbody\r\n")
    state = hud.collect_skills(ctx)
    assert skill_of(state, "demo")["tokens"] == 5, skill_of(state, "demo")
    assert skill_of(state, "demo")["desc"] == "hello --- world"
    for sid in ("unclosed", "unclosed-body", "dashes", "dashes-open"):
        s = skill_of(state, sid)
        assert s["tokens"] is None, (sid, s)
        assert {i["code"] for i in s["issues"]} & set(hud.TOKEN_INCOMPLETE), (sid, s["issues"])
    assert skill_of(state, "crlf")["tokens"] == 5, skill_of(state, "crlf")
    # 읽기 상한에서 잘린 머리말: 닫는 줄을 못 봤으니 설명이 끝까지인지 모른다
    hud.META_READ_MAX = 100
    try:
        write_skill(skills, "cut", LONG_DESC)
        write_skill(skills, "fits", "hello world")
        state = hud.collect_skills(ctx)
        assert skill_of(state, "cut")["tokens"] is None and skill_of(state, "cut")["desc"] == "", skill_of(state, "cut")
        assert skill_of(state, "fits")["tokens"] == 4
    finally:
        hud.META_READ_MAX = 1_000_000
    # 상한 안이면 8000자를 넘는 설명도 그대로 센다
    write_skill(skills, "cut", LONG_DESC)
    assert skill_of(hud.collect_skills(ctx), "cut")["tokens"] == 1502


def tokens_only_unmeasurable(tmp):
    """설명이 없는 스킬 하나뿐이면 볼 수 있는 스킬은 1, 센 스킬은 0이다. 볼 수 있는 스킬이 정말 없을 때만 0/0이다."""
    hud.HOME, hud.CLAUDE_DIR = os.path.join(tmp, "h"), os.path.join(tmp, "h", ".claude")
    os.makedirs(hud.CLAUDE_DIR)
    proj = os.path.join(tmp, "p"); os.makedirs(proj)
    write_skill(os.path.join(hud.HOME, ".agents", "skills"), "nodesc", raw="---\nname: nodesc\n---\n")
    tk = hud.collect_skills({"project_dir": proj})["tokens"]
    assert (tk["state"], tk["skills"], tk["measured"]) == ("ok", 1, 0), tk
    codex = tk["agents"]["Codex"]
    assert (codex["skills"], codex["measured"]) == (1, 0), codex
    assert (tk["agents"]["Antigravity"]["skills"], tk["agents"]["Antigravity"]["measured"]) == (0, 0)


def tokens_empty(tmp):
    hud.HOME, hud.CLAUDE_DIR = os.path.join(tmp, "h"), os.path.join(tmp, "h", ".claude")
    os.makedirs(hud.CLAUDE_DIR)
    proj = os.path.join(tmp, "p"); os.makedirs(proj)
    tk = hud.collect_skills({"project_dir": proj})["tokens"]
    assert (tk["state"], tk["skills"], tk["measured"], tk["total"]) == ("ok", 0, 0, 0), tk


def real_tokens():
    real_tokenizer()
    tokens_known_values()
    for check in (tokens_inventory, tokens_follow_real_lengths, tokens_same_file_once,
                  tokens_count_once_per_poll, tokens_frontmatter_edges, tokens_only_unmeasurable, tokens_empty):
        real_tokenizer()
        tmp = tempfile.mkdtemp()
        try:
            check(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    unit()
    end_to_end()
    tmp = tempfile.mkdtemp()
    try:
        tokens_not_measured(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if real_tokenizer():
        real_tokens()
    else:
        print("SKIP real tokenizer checks (AGENT_HUD_TEST_TOKENIZER_HOME 없음)")
    print("PASS")


if __name__ == "__main__":
    main()
