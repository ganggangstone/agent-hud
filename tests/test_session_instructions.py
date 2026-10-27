"""에이전트마다 세션을 시작할 때 늘 읽는 지침 파일을 고르는지 본다.
   - Claude Code: ~/.claude/CLAUDE.md 와 그 @가져오기, 프로젝트 루트의 CLAUDE.md·CLAUDE.local.md 와 그 @가져오기
   - Codex: ~/.codex/AGENTS.md(링크면 대상), 루트 AGENTS.override.md 가 있으면 그것, 없으면 AGENTS.md
   - Gemini CLI: ~/.gemini/GEMINI.md, 루트 GEMINI.md
   - Cursor·Copilot: 루트 AGENTS.md (Copilot 은 .github/copilot-instructions.md 도)
   - 하위 폴더의 파일과 없는 파일은 세지 않는다. 같은 파일은 한 번만 센다.
   python3 tests/test_session_instructions.py"""
import importlib.util, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def w(path, text="x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)
    return path


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    try:
        home = os.path.join(tmp, "home"); proj = os.path.join(tmp, "proj")
        hud.HOME = home; hud.CLAUDE_DIR = os.path.join(home, ".claude")
        princ = w(os.path.join(home, ".claude", "PRINCIPLES.md"))
        gclaude = w(os.path.join(home, ".claude", "CLAUDE.md"), "@PRINCIPLES.md\n@missing.md\n")
        gagents = os.path.join(home, ".codex", "AGENTS.md"); os.makedirs(os.path.dirname(gagents)); os.symlink(princ, gagents)
        pclaude = w(os.path.join(proj, "CLAUDE.md"), "@docs/RULES.md\n")
        rules = w(os.path.join(proj, "docs", "RULES.md"))
        plocal = w(os.path.join(proj, "CLAUDE.local.md"))
        pagents = w(os.path.join(proj, "AGENTS.md"))
        poverride = w(os.path.join(proj, "AGENTS.override.md"))
        copilot = w(os.path.join(proj, ".github", "copilot-instructions.md"))
        w(os.path.join(proj, "packages", "CLAUDE.md"))      # 하위 폴더: 안 센다

        got = hud.session_instructions(proj)
        assert got["Claude Code"] == [gclaude, princ, pclaude, rules, plocal], got["Claude Code"]
        assert got["Codex"] == [princ, poverride], got["Codex"]          # 링크는 대상으로, override 가 AGENTS.md 를 대신
        assert got["Gemini CLI"] == [], got["Gemini CLI"]
        assert got["Cursor"] == [pagents], got["Cursor"]
        assert got["Copilot"] == [copilot, pagents], got["Copilot"]
        assert got["Antigravity"] == [], got["Antigravity"]

        os.remove(poverride)
        assert hud.session_instructions(proj)["Codex"] == [princ, pagents]
    finally:
        shutil.rmtree(tmp)
    print("PASS")




def test_session_load():
    """에이전트마다 지침 수·스킬 수·토큰 합. 토큰은 지침 본문과 스킬 이름·설명을 더한 값이고, 하나라도 못 셌으면 None."""
    tmp = os.path.realpath(tempfile.mkdtemp())
    real = hud.count_tokens
    try:
        home = os.path.join(tmp, "home"); proj = os.path.join(tmp, "proj")
        hud.HOME = home; hud.CLAUDE_DIR = os.path.join(home, ".claude")
        w(os.path.join(proj, "CLAUDE.md"), "abcd")        # 4 "토큰"
        w(os.path.join(proj, "AGENTS.md"), "ab")           # 2
        hud.count_tokens = lambda texts: ("ok", {t: len(t) for t in texts})
        tk = {"state": "ok", "agents": {"Claude Code": {"skills": 3, "measured": 3, "tokens": 100},
                                        "Codex": {"skills": 1, "measured": 0, "tokens": 0},
                                        "Cursor": {"skills": 0, "measured": 0, "tokens": 0}}}
        load = hud.session_load(proj, tk)
        assert load["Claude Code"] == {"instructions": 1, "skills": 3, "tokens": 104}, load["Claude Code"]
        assert load["Codex"] == {"instructions": 1, "skills": 1, "tokens": None}, load["Codex"]   # 스킬을 못 셈
        assert load["Cursor"] == {"instructions": 1, "skills": 0, "tokens": 2}, load["Cursor"]
        assert load["Antigravity"] == {"instructions": 0, "skills": 0, "tokens": 0}, load["Antigravity"]
        hud.count_tokens = lambda texts: ("setup", {})
        assert hud.session_load(proj, {"state": "setup", "agents": {}})["Claude Code"]["tokens"] is None
    finally:
        hud.count_tokens = real
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
    test_session_load()
    print("PASS")
