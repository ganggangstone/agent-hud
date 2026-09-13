"""_instruction_rows()가 목록에 있는 것만, 있는 것은 전부, 밑까지 찾는지 본다.
   그리고 가지치기·상한이 실제로 걸리는지도 본다.
   python3 tests/test_instructions.py"""
import importlib.util, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)

FLAT = [rel for rel, _ in hud.INSTRUCTION_SOURCES if not rel.endswith("/")]
DIRS = [rel for rel, _ in hud.INSTRUCTION_SOURCES if rel.endswith("/")]


def build(root):
    for rel in FLAT:
        p = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(p) or root, exist_ok=True)
        open(p, "w").write("x")
    for rel in DIRS:
        d = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "a.md"), "w").write("x")
        open(os.path.join(d, "logo.png"), "w").write("x")
    open(os.path.join(root, "NOTES.md"), "w").write("x")


def main():
    root = tempfile.mkdtemp()
    try:
        build(root)
        # 밑에 있는 것도 찾아야 한다. Claude Code 자신이 하위 CLAUDE.md를 읽는다.
        deep = os.path.join(root, "packages", "web", "src")
        os.makedirs(deep)
        open(os.path.join(deep, "CLAUDE.md"), "w").write("x")
        open(os.path.join(root, "packages", "AGENTS.md"), "w").write("x")
        # 가지치기 대상은 안에 있어도 안 잡혀야 한다
        junk = os.path.join(root, "node_modules", "pkg")
        os.makedirs(junk)
        open(os.path.join(junk, "CLAUDE.md"), "w").write("x")

        hud._scan_cache.clear()
        rows, truncated = hud._instruction_rows(root)
        names = {r["name"] for r in rows}
        assert not truncated, "이 정도 크기에서 잘리면 상한이 너무 빡빡하다"
        missing = (set(FLAT) | {d + "a.md" for d in DIRS}) - names
        assert not missing, f"찾지 못한 파일: {sorted(missing)}"
        assert "packages/web/src/CLAUDE.md" in names, "깊은 곳의 CLAUDE.md를 못 찾았다"
        assert "packages/AGENTS.md" in names, "하위의 AGENTS.md를 못 찾았다"
        assert not [n for n in names if "node_modules" in n], "가지치기가 안 됐다"
        assert "NOTES.md" not in names, "목록에 없는 파일이 새어 들어옴"
        assert not [n for n in names if n.endswith(".png")], "확장자 필터가 안 걸린다"
        assert "CLAUDE.md" not in names, "루트 CLAUDE.md는 위쪽 고정 행이 따로 보여준다"
        assert all(r["exists"] and r["tool"] for r in rows), "exists/tool 누락"

        # 상한이 실제로 멈추는지 (그리고 멈춘 사실을 알려주는지)
        budget = hud.SCAN_DIR_BUDGET
        try:
            hud.SCAN_DIR_BUDGET = 3
            hud._scan_cache.clear()
            _, trunc2 = hud._instruction_rows(root)
            assert trunc2, "상한을 넘겼는데 잘렸다고 말하지 않는다"
        finally:
            hud.SCAN_DIR_BUDGET = budget

        hud._scan_cache.clear()
        assert hud._instruction_rows(os.path.join(root, "nope"))[0] == [], "없는 디렉터리에서 행이 생김"
        print(f"PASS ({len(rows)} rows)")
    finally:
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
