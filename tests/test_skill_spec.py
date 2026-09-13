"""_skill_meta()가 공개 명세 위반을 잡는지 본다.
   위반은 '로드 실패'가 아니라 '명세 위반'이다 -- 이름을 그렇게 유지할 것.
   python3 tests/test_skill_spec.py"""
import importlib.util, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def write(root, folder, text):
    d = os.path.join(root, folder)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "SKILL.md")
    open(p, "w", encoding="utf-8").write(text)
    return p, folder


def codes(root, folder, text):
    p, f = write(root, folder, text)
    return [i["code"] for i in hud._skill_meta(p, f)[2]]


def main():
    tmp = tempfile.mkdtemp()
    try:
        ok = "---\nname: good-skill\ndescription: Does a thing. Use when you need it.\n---\nbody\n"
        assert codes(tmp, "good-skill", ok) == [], "멀쩡한 스킬에 위반이 붙었다"

        assert "no_frontmatter" in codes(tmp, "bare", "just text, no frontmatter\n")
        assert "name_missing" in codes(tmp, "noname", "---\ndescription: x\n---\n")
        assert "name_mismatch" in codes(tmp, "folder-a", "---\nname: other-name\ndescription: x\n---\n")
        assert "name_format" in codes(tmp, "Bad_Name", "---\nname: Bad_Name\ndescription: x\n---\n")
        assert "name_format" in codes(tmp, "dbl", "---\nname: a--b\ndescription: x\n---\n")
        assert "desc_missing" in codes(tmp, "nodesc", "---\nname: nodesc\n---\n")

        long_desc = "x" * (hud.DESC_MAX + 5)
        got = codes(tmp, "longdesc", f"---\nname: longdesc\ndescription: {long_desc}\n---\n")
        assert "desc_long" in got, got
        # 상한 바로 아래는 걸리면 안 된다
        just_ok = "x" * hud.DESC_MAX
        assert "desc_long" not in codes(tmp, "edge", f"---\nname: edge\ndescription: {just_ok}\n---\n")

        # 접힌 블록 스칼라도 길이를 재야 한다
        folded = "---\nname: folded\ndescription: >-\n" + "".join(
            "  " + "y" * 80 + "\n" for _ in range(14)) + "---\n"
        assert "desc_long" in codes(tmp, "folded", folded), "접힌 블록의 길이를 안 쟀다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
