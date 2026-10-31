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

        # 3. CLAUDE.md의 @가져오기: 상대 경로는 그 파일 옆, ~는 홈. 문장 속 @는 파일이 있을 때만 보여 준다.
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


def test_import_rules():
    """Claude Code v2.1.314에서 센티널로 측정한 @가져오기 규칙."""
    tmp = os.path.realpath(tempfile.mkdtemp())
    try:
        def w(rel, text="x\n"):
            path = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").write(text)
            return path
        names = ["inline.md", "quoted.md", "span.md", "fence.md", "tilde.md", "email.md", "UPPER.txt"]
        inline, quoted, span, fence, tilde, email, upper = [w(n) for n in names]
        space = w("dir sp/space.md")
        claude = w("CLAUDE.md", "see @inline.md please\n@\"quoted.md\"\n`@span.md`\n```\n@fence.md\n```\n"
                               "~~~\n@tilde.md\n~~~\n@dir\\ sp/space.md\n@UPPER.txt\nme@email.md\n")
        got = hud._imports_of(claude)
        assert got == [claude, inline, space, upper], got
        link = hud._link_info(claude)
        assert [t["path"] for t in link["targets"]] == [inline, space, upper], link

        # 줄 맨 앞인데 없는 파일은 깨진 연결로 보여 주고, 문장 속이면 그냥 글자다.
        broken = w("b/CLAUDE.md", "@gone.md\nask @nobody here\n")
        assert [t["ok"] for t in hud._link_info(broken)["targets"]] == [False]

        # 네 단계까지 따라가고, 이름이 CLAUDE.md가 아니어도 해석한다. 순환은 멈춘다.
        h = [w(f"d/h{i}.md", f"@h{i+1}.md\n") for i in range(1, 6)]
        w("d/h6.md")
        root = w("d/CLAUDE.md", "@h1.md\n")
        assert hud._imports_of(root) == [root] + h[:4], hud._imports_of(root)
        a = w("c/CLAUDE.md", "@a.md\n"); aa = w("c/a.md", "@CLAUDE.md\n")
        assert hud._imports_of(a) == [a, aa], hud._imports_of(a)

        # 링크의 상대 경로는 대상 파일 기준이고, 링크된 파일 안의 @도 따라간다.
        os.makedirs(os.path.join(tmp, "l/sub"))
        w("l/side.md"); side = w("l/sub/side.md"); real = w("l/sub/REAL.md", "@side.md\n")
        ln = os.path.join(tmp, "l/CLAUDE.md"); os.symlink("sub/REAL.md", ln)
        assert hud._imports_of(ln) == [real, side], hud._imports_of(ln)

        # 목록: 여러 단계의 대상도 행이 되고, 행마다 자기 연결을 보여 준다.
        rows = hud._with_link_targets([hud._file_row("CLAUDE.md", root)])
        by = {r["path"]: r for r in rows}
        assert list(by) == [root] + h[:4], list(by)
        assert by[h[0]]["link"]["targets"][0]["path"] == h[1]
        assert by[h[3]]["link"]["targets"][0]["path"] == h[4], "네 번째 파일은 연결을 보여 주되 다섯 번째 행은 만들지 않는다"

        # 다른 도구의 파일이어도 CLAUDE.md가 가져오면 그 안의 @도 Claude Code가 읽는다.
        agents = w("e/AGENTS.md", "@more.md\n"); more = w("e/more.md")
        top = w("e/CLAUDE.md", "@AGENTS.md\n")
        by = {r["path"]: r for r in hud._with_link_targets([hud._file_row("CLAUDE.md", top), hud._file_row("AGENTS.md", agents, "Codex")])}
        assert more in by and by[agents]["link"]["targets"][0]["path"] == more, by
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
    test_targets_become_rows()
    test_import_rules()
    print("ok")
