"""지침 파일 행에 연결 상태(link)가 붙는지 본다.
   심볼릭 링크면 대상과 실재 여부, CLAUDE.md 계열이면 `@경로` 줄이 가져오는 파일 목록,
   둘 다 아니면 None(독립 파일). 어느 쪽이 원본인지는 판단하지 않는다.
   python3 tests/test_instruction_links.py"""
import importlib.util, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def main():
    tmp = tempfile.mkdtemp()
    try:
        src = os.path.join(tmp, "AGENTS.md")
        open(src, "w").write("# rules\n")

        # 1. 독립 파일
        assert hud._file_row("AGENTS.md", src)["link"] is None

        # 2. 심볼릭 링크: 대상이 있을 때 / 없을 때
        ok = os.path.join(tmp, "GEMINI.md")
        os.symlink(src, ok)
        row = hud._file_row("GEMINI.md", ok)
        assert row["link"] == {"kind": "symlink", "target": src, "ok": True}, row["link"]
        broken = os.path.join(tmp, "QWEN.md")
        os.symlink(os.path.join(tmp, "gone.md"), broken)
        assert hud._file_row("QWEN.md", broken)["link"]["ok"] is False

        # 3. CLAUDE.md의 @가져오기: 상대 경로는 그 파일 옆, ~는 홈. 줄 첫머리 @만 센다.
        claude = os.path.join(tmp, "CLAUDE.md")
        open(claude, "w").write("@AGENTS.md\n@~/.nope/none.md\nemail me @home\n")
        link = hud._file_row("CLAUDE.md", claude)["link"]
        assert link["kind"] == "import", link
        assert link["targets"] == [
            {"path": src, "ok": True},
            {"path": os.path.expanduser("~/.nope/none.md"), "ok": False},
        ], link["targets"]

        # 4. @는 Claude Code 파일에서만 해석한다 (다른 도구는 따르지 않는다)
        other = os.path.join(tmp, "WARP.md")
        open(other, "w").write("@AGENTS.md\n")
        assert hud._file_row("WARP.md", other, "Warp")["link"] is None

        # 5. 없는 파일
        assert hud._file_row("x", os.path.join(tmp, "nope.md"))["link"] is None
    finally:
        shutil.rmtree(tmp)




def test_targets_become_rows():
    """링크·@가 가리키는 파일은 목록에 없어도 행으로 보인다. 이미 있는 행은 두 번 넣지 않는다."""
    tmp = tempfile.mkdtemp()
    try:
        src = os.path.join(tmp, "PRINCIPLES.md"); open(src, "w").write("p\n")
        agents = os.path.join(tmp, "AGENTS.md"); open(agents, "w").write("a\n")
        claude = os.path.join(tmp, "CLAUDE.md"); open(claude, "w").write("@PRINCIPLES.md\n@AGENTS.md\n@missing.md\n")
        gem = os.path.join(tmp, "GEMINI.md"); os.symlink(src, gem)
        rows = [hud._file_row("CLAUDE.md", claude), hud._file_row("AGENTS.md", agents, "Codex"),
                hud._file_row("GEMINI.md", gem, "Gemini CLI")]
        out = hud._with_link_targets(rows)
        paths = [r["path"] for r in out]
        assert paths[:3] == [claude, agents, gem], paths
        assert paths.count(src) == 1 and paths.count(agents) == 1, paths   # 중복 없음
        assert os.path.join(tmp, "missing.md") not in paths                 # 없는 대상은 행으로 안 만든다
        added = out[3]
        assert added["name"] == src and added["tool"] == "" and added["via"] == ["CLAUDE.md", "GEMINI.md"], added
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
    test_targets_become_rows()
    print("ok")
