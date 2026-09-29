"""한 프로젝트 안에만 있는 스킬도 그룹에 넣어 다른 프로젝트에 걸 수 있는지 본다.
- 원본으로 받는 건 등록된 프로젝트 안의 실제 폴더뿐이다. 링크를 원본으로 받으면 링크를
  가리키는 링크가 생긴다.
- 이름이 겹치면 플러그인·사용자 스킬 폴더가 이긴다.
- 원본 프로젝트에서는 실제 폴더를 건드리지 않고, 그 자리도 '보이는' 것으로 센다.
   python3 tests/test_project_skill_source.py"""
import importlib.util, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def make_skill(root, name):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: x\n---\n")
    return d


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    try:
        home = os.path.join(tmp, "home"); os.makedirs(home)
        hud.HOME = home
        a, b, c = (os.path.join(tmp, n) for n in ("A", "B", "C"))
        for p in (a, b, c):
            os.makedirs(p)
        hud.known_projects = lambda: [a, b, c]
        hud.plugin_skills = lambda: {"P": {"clash": make_skill(os.path.join(tmp, "plug"), "clash")}}

        own = make_skill(os.path.join(a, ".claude", "skills"), "only-in-a")
        make_skill(os.path.join(a, ".claude", "skills"), "clash")
        # B에는 A를 가리키는 링크만 있다. 이것은 원본이 아니다.
        os.makedirs(os.path.join(b, ".claude", "skills"))
        os.symlink(own, os.path.join(b, ".claude", "skills", "only-in-b-link"))

        src = hud.skill_sources(c)
        assert src.get("only-in-a") == own, "프로젝트 안의 실제 스킬을 원본으로 못 받았다"
        assert "only-in-b-link" not in src, "링크를 원본으로 받았다"
        assert src["clash"].startswith(os.path.join(tmp, "plug")), "이름이 겹칠 때 플러그인이 이기지 않았다"

        # 다른 프로젝트(C)에 걸면 A의 원본을 가리키는 링크가 생긴다
        ok, err = hud.link_skill("only-in-a", True, c)
        assert ok, err
        assert hud.skill_is_shared(c, "only-in-a"), "C의 스킬 폴더에 안 걸렸다"
        assert os.path.realpath(hud._link_path(c, ".claude/skills", "only-in-a")) == own

        # 원본 프로젝트(A)에서는 실제 폴더를 두고 빈 자리만 채운다
        ok, err = hud.link_skill("only-in-a", True, a)
        assert ok, err
        assert not os.path.islink(own) and os.path.isfile(os.path.join(own, "SKILL.md")), "원본을 건드렸다"
        assert hud.skill_is_shared(a, "only-in-a"), "원본이 있는 자리를 '보인다'로 세지 않았다"
        hud.link_skill("only-in-a", False, a)
        assert os.path.isfile(os.path.join(own, "SKILL.md")), "끌 때 원본을 지웠다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
