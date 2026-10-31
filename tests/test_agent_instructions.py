"""에이전트별로 세션 시작 때 읽는 지침과 스킬이 측정·문서와 맞는지 본다.
   python3 tests/test_agent_instructions.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def w(path, text="x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)
    return path


def env():
    tmp = os.path.realpath(tempfile.mkdtemp())
    hud.HOME = os.path.join(tmp, "home"); hud.CLAUDE_DIR = os.path.join(hud.HOME, ".claude")
    os.environ.pop("CODEX_HOME", None)
    return tmp

def test_plugin_row_group_chip_both_formats():
    tmp = env()
    try:
        d = os.path.join(hud.CLAUDE_DIR, "plugins"); ip = os.path.join(tmp, "pl")
        os.makedirs(os.path.join(ip, "skills"))
        w(os.path.join(d, "installed_plugins.json"), json.dumps({"plugins": {"p@m": [{"installPath": ip, "version": "1"}]}}))
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        for fmt in ({"g": ["p@m"]}, {"g": {"plugins": ["p@m"], "skills": []}}):
            json.dump(fmt, open(hud.MODES_FILE, "w"))
            row = [r for r in hud.collect_skills({"project_dir": tmp})["rows"] if r["name"] == "p@m"][0]
            assert row["modes"] == ["g"], (fmt, row["modes"])
    finally:
        shutil.rmtree(tmp)


def test_codex_skips_empty_override():
    tmp = env()
    try:
        proj = os.path.join(tmp, "p"); real = w(os.path.join(proj, "AGENTS.md"))
        w(os.path.join(proj, "AGENTS.override.md"), "")
        assert hud.session_instructions(proj)["Codex"] == [real]
        over = w(os.path.join(proj, "AGENTS.override.md"))
        assert hud.session_instructions(proj)["Codex"] == [over]
        gl = w(os.path.join(hud.HOME, ".codex", "AGENTS.md")); go = w(os.path.join(hud.HOME, ".codex", "AGENTS.override.md"))
        assert hud.session_instructions(proj)["Codex"] == [go, over]
    finally:
        shutil.rmtree(tmp)


def test_codex_walks_from_git_root():
    tmp = env()
    try:
        repo = os.path.join(tmp, "r"); os.makedirs(os.path.join(repo, ".git"))
        w(os.path.join(tmp, "AGENTS.md"))                # 저장소 밖: 안 읽는다
        top = w(os.path.join(repo, "AGENTS.md")); leaf = w(os.path.join(repo, "pkg", "a", "AGENTS.md"))
        assert hud.session_instructions(os.path.join(repo, "pkg", "a"))["Codex"] == [top, leaf]
        os.rmdir(os.path.join(repo, ".git"))             # 루트가 없으면 현재 폴더만
        assert hud.session_instructions(os.path.join(repo, "pkg", "a"))["Codex"] == [leaf]
        os.environ["CODEX_HOME"] = os.path.join(tmp, "ch")
        ch = w(os.path.join(tmp, "ch", "AGENTS.md"))
        assert hud.session_instructions(os.path.join(repo, "pkg", "a"))["Codex"] == [ch, leaf]
    finally:
        os.environ.pop("CODEX_HOME", None)
        shutil.rmtree(tmp)


def test_agy_cli_skill_paths():
    tmp = env()
    try:
        base = os.path.join(hud.HOME, ".gemini", "antigravity-cli")
        w(os.path.join(base, "skills", "cli-skill", "SKILL.md"), "---\nname: cli-skill\ndescription: x\n---\n")
        w(os.path.join(base, "plugins", "pg", "skills", "pl-skill", "SKILL.md"), "---\nname: pl-skill\ndescription: x\n---\n")
        idx = hud._skill_root_index(tmp)
        assert idx["cli-skill"]["agents"] == ["Antigravity"], idx
        assert idx["pl-skill"]["agents"] == ["Antigravity"], idx
    finally:
        shutil.rmtree(tmp)


def test_claude_hierarchy_and_rules():
    tmp = env()
    try:
        a = os.path.join(tmp, "a"); p = os.path.join(a, "p"); os.makedirs(p)
        par = w(os.path.join(a, "CLAUDE.md")); pdot = w(os.path.join(a, ".claude", "CLAUDE.md"))
        prule = w(os.path.join(a, ".claude", "rules", "r.md")); ploc = w(os.path.join(a, "CLAUDE.local.md"))
        w(os.path.join(a, "AGENTS.md")); w(os.path.join(p, "AGENTS.md"))
        dot = w(os.path.join(p, ".claude", "CLAUDE.md")); deep = w(os.path.join(p, ".claude", "rules", "deep", "d.md"))
        top = w(os.path.join(p, ".claude", "rules", "top.md"))
        w(os.path.join(p, ".claude", "rules", "scoped.md"), "---\npaths:\n  - \"**/*.zzz\"\n---\nx\n")
        w(os.path.join(p, ".claude", "rules", "n.txt")); loc = w(os.path.join(p, "CLAUDE.local.md"))
        w(os.path.join(p, "sub", "CLAUDE.md"))
        ur = w(os.path.join(hud.CLAUDE_DIR, "rules", "u.md"))
        got = hud.session_instructions(p)["Claude Code"]
        assert got == [ur, par, pdot, prule, ploc, dot, deep, top, loc], got
        rows = {r["path"]: r for r in hud.collect_instructions({"project_dir": p})["files"]}
        for f in got:
            assert f in rows, f
        assert rows[dot]["scope"] == "project" and rows[par]["scope"] == "global"
    finally:
        shutil.rmtree(tmp)


def test_claude_reads_agents_only_without_claude_md():
    tmp = env()
    try:
        b = os.path.join(tmp, "b"); q = os.path.join(b, "q"); os.makedirs(q)
        pa = w(os.path.join(b, "AGENTS.md")); qa = w(os.path.join(q, "AGENTS.md")); qd = w(os.path.join(q, ".claude", "AGENTS.md"))
        gl = w(os.path.join(hud.CLAUDE_DIR, "CLAUDE.md"))   # 전역 CLAUDE.md는 대체 판정에 안 들어간다
        assert hud.session_instructions(q)["Claude Code"] == [gl, pa, qa, qd]
        c = w(os.path.join(b, "CLAUDE.md"))
        assert hud.session_instructions(q)["Claude Code"] == [gl, c]
    finally:
        shutil.rmtree(tmp)


#TESTS

if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
    print("PASS")
