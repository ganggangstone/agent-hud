"""_instruction_rows()가 목록에 있는 것만, 있는 것은 전부 찾는지 본다.
   python3 test_instructions.py"""
import importlib.util, os, shutil, tempfile

spec = importlib.util.spec_from_file_location("hud", os.path.join(os.path.dirname(__file__), "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def build(root):
    for rel, _ in hud.INSTRUCTION_SOURCES:
        p = os.path.join(root, rel.replace("/", os.sep))
        if rel.endswith("/"):
            os.makedirs(p, exist_ok=True)
            open(os.path.join(p, "a.md"), "w").write("x")
            open(os.path.join(p, "logo.png"), "w").write("x")
        else:
            os.makedirs(os.path.dirname(p) or root, exist_ok=True)
            open(p, "w").write("x")
    open(os.path.join(root, "NOTES.md"), "w").write("x")


def main():
    root = tempfile.mkdtemp()
    try:
        build(root)
        rows = hud._instruction_rows(root)
        names = {r["name"] for r in rows}
        files = {rel for rel, _ in hud.INSTRUCTION_SOURCES if not rel.endswith("/")}
        dirs = {rel for rel, _ in hud.INSTRUCTION_SOURCES if rel.endswith("/")}
        missing = (files | {d + "a.md" for d in dirs}) - names
        assert not missing, f"찾지 못한 파일: {sorted(missing)}"
        assert "NOTES.md" not in names, "목록에 없는 파일이 새어 들어옴"
        assert not [n for n in names if n.endswith(".png")], "확장자 필터가 안 걸린다"
        assert all(r["exists"] and r["tool"] for r in rows), "exists/tool 누락"
        assert hud._instruction_rows(os.path.join(root, "nope")) == [], "없는 디렉터리에서 행이 생김"
        print(f"PASS ({len(rows)} rows)")
    finally:
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
