"""에이전트마다 세션을 시작할 때 늘 읽는 지침 파일을 고르는지 본다.
   - Claude Code: ~/.claude/CLAUDE.md 와 그 @가져오기, 프로젝트 루트의 CLAUDE.md·CLAUDE.local.md 와 그 @가져오기
   - Codex: ~/.codex/AGENTS.md(링크면 대상), 루트 AGENTS.override.md 가 있으면 그것, 없으면 AGENTS.md
   - Gemini CLI: ~/.gemini/GEMINI.md, 루트 GEMINI.md
   - Cursor·Copilot: 루트 AGENTS.md (Copilot 은 .github/copilot-instructions.md 도)
   - 하위 폴더의 파일과 없는 파일은 세지 않는다. 같은 파일은 한 번만 센다.
   - Claude Code는 claudeMdExcludes에 걸린 파일과 그 파일의 @가져오기를 세지 않는다. 다른 에이전트는 상관없다.
   python3 tests/test_session_instructions.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("CODEX_HOME", None)   # 이 셸의 실제 Codex 폴더를 읽지 않게 한다
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
        assert got["Antigravity"] == [pagents], got["Antigravity"]

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
        assert load["Antigravity"] == {"instructions": 1, "skills": 0, "tokens": 2}, load["Antigravity"]
        hud.count_tokens = lambda texts: ("setup", {})
        assert hud.session_load(proj, {"state": "setup", "agents": {}})["Claude Code"]["tokens"] is None
    finally:
        hud.count_tokens = real
        shutil.rmtree(tmp)


def test_claude_md_excludes():
    """설정 계층의 배열을 합쳐 적용하고, 지침 목록에는 지우지 않고 제외됐다고 표시한다."""
    tmp = os.path.realpath(tempfile.mkdtemp())
    try:
        home = os.path.join(tmp, "home"); proj = os.path.join(tmp, "proj")
        hud.HOME = home; hud.CLAUDE_DIR = os.path.join(home, ".claude")
        rtk = w(os.path.join(home, ".claude", "RTK.md"))
        gagents = w(os.path.join(home, ".codex", "AGENTS.md"))
        gclaude = w(os.path.join(home, ".claude", "CLAUDE.md"), "@~/.codex/AGENTS.md\n@RTK.md\n")
        pclaude = w(os.path.join(proj, "CLAUDE.md"), "@AGENTS.md\n@shared.md\n")
        pagents = w(os.path.join(proj, "AGENTS.md"))
        shared = w(os.path.join(proj, "shared.md"))
        real_expand = os.path.expanduser
        os.path.expanduser = lambda q: q.replace("~", home, 1) if q.startswith("~") else real_expand(q)

        w(os.path.join(proj, ".claude", "settings.local.json"), json.dumps({"claudeMdExcludes": [gclaude]}))
        got = hud.session_instructions(proj)
        assert got["Claude Code"] == [pclaude, pagents, shared], got["Claude Code"]    # 제외한 파일의 @대상도 안 읽힌다
        assert got["Codex"] == [gagents, pagents], got["Codex"]                         # Codex는 설정을 읽지 않는다

        rows = {r["path"]: r for r in hud.collect_instructions({"project_dir": proj})["files"]}
        assert rows[gclaude]["claude_excluded"] is True
        assert rows[rtk]["claude_excluded"] is True, "제외한 파일로만 닿는 @대상도 안 읽힌다"
        assert rows[pclaude]["claude_excluded"] is False
        assert rows[gagents]["claude_excluded"] is False, "Codex 파일 행: 직접 제외하지 않았다"

        # 다른 도구의 파일은 그 경로를 직접 제외했을 때만 표시한다. 링크 대상이 제외돼도 Claude Code와 무관하다.
        ggemini = os.path.join(home, ".gemini", "GEMINI.md"); os.makedirs(os.path.dirname(ggemini)); os.symlink(gagents, ggemini)
        w(os.path.join(proj, ".claude", "settings.local.json"), json.dumps({"claudeMdExcludes": [gclaude, gagents]}))
        rows = {r["path"]: r for r in hud.collect_instructions({"project_dir": proj})["files"]}
        assert rows[gagents]["claude_excluded"] is True
        assert rows[ggemini]["claude_excluded"] is False

        # 계층 합치기와 ** 패턴. 패턴은 절대 경로에 맞춘다.
        w(os.path.join(home, ".claude", "settings.json"), json.dumps({"claudeMdExcludes": ["**/proj/shared.md"]}))
        w(os.path.join(proj, ".claude", "settings.json"), json.dumps({"claudeMdExcludes": ["**/proj/AGENT?.md"]}))
        got = hud.session_instructions(proj)["Claude Code"]
        assert got == [pclaude], got

        # * 는 폴더 경계를 넘지 않는다
        w(os.path.join(proj, ".claude", "settings.local.json"), json.dumps({"claudeMdExcludes": [tmp + "/*.md"]}))
        os.remove(os.path.join(home, ".claude", "settings.json"))
        os.remove(os.path.join(proj, ".claude", "settings.json"))
        assert gclaude in hud.session_instructions(proj)["Claude Code"]

        # 링크는 링크 경로와 대상 경로 어느 쪽으로도 제외된다
        os.remove(pclaude); os.symlink(shared, pclaude)
        w(os.path.join(proj, ".claude", "settings.local.json"), json.dumps({"claudeMdExcludes": [pclaude]}))
        assert shared not in hud.session_instructions(proj)["Claude Code"]
        w(os.path.join(proj, ".claude", "settings.local.json"), json.dumps({"claudeMdExcludes": [shared]}))
        assert shared not in hud.session_instructions(proj)["Claude Code"]

        # managed 설정의 배열도 합친다
        managed = w(os.path.join(tmp, "managed", "managed-settings.json"), json.dumps({"claudeMdExcludes": [shared]}))
        hud.MANAGED_SETTINGS = managed
        w(os.path.join(proj, ".claude", "settings.local.json"), "{}")
        assert shared not in hud.session_instructions(proj)["Claude Code"]
        os.remove(managed)

        # 문자 클래스
        assert hud._glob_regex("/r/[ab]/C.md").fullmatch("/r/a/C.md")
        assert not hud._glob_regex("/r/[ab]/C.md").fullmatch("/r/c/C.md")
        assert hud._glob_regex("/r/[!ab]/C.md").fullmatch("/r/c/C.md")
        assert hud._glob_regex("/r/[x.md").fullmatch("/r/[x.md"), "닫히지 않은 [ 는 글자 그대로"

        # 잘못된 값은 무시한다
        w(os.path.join(proj, ".claude", "settings.local.json"), json.dumps({"claudeMdExcludes": "x"}))
        assert shared in hud.session_instructions(proj)["Claude Code"]
        os.path.expanduser = real_expand
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
    test_session_load()
    test_claude_md_excludes()
    print("PASS")
