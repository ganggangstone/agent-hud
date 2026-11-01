"""프로젝트가 .agents/skills를 .claude/skills로 링크해 둔 경우를 본다.
   두 이름이 한 폴더이므로 모든 에이전트가 이미 스킬을 본다. 공유 상태가 그렇게 나와야 하고,
   켜고 끄기도 그 한 폴더에서 끝나야 한다. 프로젝트 밖이나 다른 폴더로 가는 링크는 계속 막는다.
   이름이 겹쳐 행 id에 @가 붙은 스킬을 이름 불일치로 경고하지 않는지도 본다.
   python3 tests/test_skill_dir_alias.py"""
import importlib.util, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def make_skill(root, folder, name=None, desc="x"):
    d = os.path.join(root, folder)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name or folder}\ndescription: {desc}\n---\n")
    return d


def alias_project(tmp, name):
    proj = os.path.join(tmp, name)
    os.makedirs(os.path.join(proj, ".claude", "skills"))
    os.makedirs(os.path.join(proj, ".agents"))
    os.symlink(os.path.join("..", ".claude", "skills"), os.path.join(proj, ".agents", "skills"))
    return proj


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    try:
        home = os.path.join(tmp, "home")
        hud.HOME = home
        hud.CLAUDE_DIR = os.path.join(home, ".claude")
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        hud.SETS_FILE = os.path.join(tmp, "sets.json")
        hud.plugin_skills = lambda: {}
        global_skill = make_skill(os.path.join(home, ".claude", "skills"), "from-home")

        # 프로젝트 안의 스킬은 이미 모든 에이전트에게 열려 있다
        proj = alias_project(tmp, "proj")
        own = make_skill(os.path.join(proj, ".claude", "skills"), "own")
        hud.known_projects = lambda: [proj]
        assert hud.skill_is_shared(proj, "own"), "링크로 묶인 폴더의 스킬이 공유 안 됨으로 나온다"
        ok, err = hud.link_skill("own", True, proj)
        assert ok, err
        assert not os.path.islink(own), "진짜 폴더를 링크로 바꿨다"

        # 전역 스킬은 한 폴더에 링크 하나로 켜지고, 끄면 흔적 없이 사라진다
        link = os.path.join(proj, ".claude", "skills", "from-home")
        ok, err = hud.link_skill("from-home", True, proj)
        assert ok, err
        assert os.path.islink(link) and hud.skill_is_shared(proj, "from-home"), "켜지지 않았다"
        ok, err = hud.link_skill("from-home", False, proj)
        assert ok, err
        assert not os.path.lexists(link) and not hud.skill_is_shared(proj, "from-home"), "꺼지지 않았다"
        assert os.path.isfile(os.path.join(global_skill, "SKILL.md")), "원본을 지웠다"

        # 링크가 스킬 폴더가 아닌 곳을 가리키면 그대로 막는다
        other = os.path.join(tmp, "other")
        os.makedirs(os.path.join(other, "docs"))
        os.makedirs(os.path.join(other, ".agents"))
        os.symlink(os.path.join("..", "docs"), os.path.join(other, ".agents", "skills"))
        assert hud._skill_path_state(other, ".agents/skills", "from-home", global_skill) == "blocked"
        assert not hud.link_skill("from-home", True, other)[0], "다른 폴더로 가는 링크에 썼다"
        assert os.listdir(os.path.join(other, "docs")) == [], "다른 폴더에 링크가 생겼다"

        # 서로를 가리키는 링크도 막는다
        loop = os.path.join(tmp, "loop")
        os.makedirs(os.path.join(loop, ".claude"))
        os.makedirs(os.path.join(loop, ".agents"))
        os.symlink(os.path.join("..", ".agents", "skills"), os.path.join(loop, ".claude", "skills"))
        os.symlink(os.path.join("..", ".claude", "skills"), os.path.join(loop, ".agents", "skills"))
        assert hud._skill_path_state(loop, ".agents/skills", "from-home", global_skill) == "blocked"

        # 전역에서 내용이 다른 같은 이름 스킬. 폴더 이름과 name이 같으니 경고할 게 없다
        make_skill(os.path.join(home, ".cursor", "skills"), "from-home", desc="다른 내용")
        make_skill(os.path.join(home, ".cursor", "skills"), "folder-a", name="name-b")
        plain = os.path.join(tmp, "plain"); os.makedirs(plain)
        rows = [r for r in hud.collect_skills({"project_dir": plain})["rows"] if not r["name"]][0]["skills"]
        by_id = {s["id"]: s for s in rows}
        assert by_id["from-home@~/.cursor/skills"]["issues"] == [], "겹친 이름의 행을 이름 불일치로 경고한다"
        assert [i["code"] for i in by_id["folder-a"]["issues"]] == ["name_mismatch"], "진짜 불일치를 놓쳤다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
