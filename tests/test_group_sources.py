"""이름이 같은 스킬이 여럿일 때 그룹이 고른 파일을 쓰는지, 일부만 적용되면 알리는지 본다.
   python3 tests/test_group_sources.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def make_skill(root, name, desc="x"):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: {desc}\n---\n")
    return d


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    try:
        os.environ.pop("CODEX_HOME", None)
        home = os.path.join(tmp, "home")
        hud.HOME = home
        hud.CLAUDE_DIR = os.path.join(home, ".claude")
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        hud.SETS_FILE = os.path.join(tmp, "sets.json")
        hud.LINK_DIRS_FILE = os.path.join(tmp, "link-dirs.json")
        plug = os.path.join(tmp, "plug")
        from_plugin = make_skill(os.path.join(plug, "skills"), "same", "plugin copy")
        mine = make_skill(os.path.join(home, ".claude", "skills"), "same", "my copy")
        make_skill(os.path.join(home, ".agents", "skills"), "same", "my copy")     # 내용이 같으면 선택지가 늘지 않는다
        make_skill(os.path.join(home, ".claude", "skills"), "plain")
        os.makedirs(os.path.join(home, ".claude", "plugins"))
        json.dump({"plugins": {"p@m": [{"installPath": plug, "version": "1"}]}},
                  open(os.path.join(home, ".claude", "plugins", "installed_plugins.json"), "w"))
        proj = os.path.join(tmp, "proj"); os.makedirs(proj)
        hud.PROJECT_DIR = proj
        hud.known_projects = lambda: [proj]
        link = os.path.join(proj, ".agents", "skills", "same")

        # 고를 수 있는 파일을 알려 준다. 하나뿐인 이름은 고를 것이 없다
        choices = hud.collect_groups({"project_dir": proj})["skill_choices"]
        assert sorted(c["source"] for c in choices["same"]) == sorted([from_plugin, mine]), choices
        assert "plain" not in choices

        # 없는 경로는 받지 않는다
        assert not hud.modify_group("add", "g", "same", "skill", source=os.path.join(tmp, "nope"))[0]

        # 고른 파일을 링크한다. 고르지 않으면 지금까지처럼 플러그인 쪽이다
        ok, err = hud.modify_group("add", "g", "same", "skill", source=mine)
        assert ok, err
        ok, err = hud.modify_group("add", "h", "same", "skill")
        assert ok, err
        ok, err = hud.assign_set("g", proj)
        assert ok, err
        assert os.path.realpath(link) == mine, "고른 파일이 아니다"
        member = [g for g in hud.collect_groups({"project_dir": proj})["groups"] if g["name"] == "g"][0]["members"][0]
        assert member["on"] and member["source"] == mine, member

        # 그룹을 바꾸면 그쪽 파일로 바뀌고, 해제하면 사라진다
        ok, err = hud.assign_set("h", proj)
        assert ok, err
        assert os.path.realpath(link) == from_plugin, "그룹을 바꿔도 이전 파일을 가리킨다"
        ok, err = hud.assign_set("", proj)
        assert ok, err
        assert not os.path.lexists(link), "해제해도 링크가 남았다"

        # 멤버를 빼면 고른 경로도 지운다
        ok, err = hud.modify_group("remove", "g", "same", "skill")
        assert ok, err
        assert "g" not in hud.read_sets()

        # 그룹에서 빠지는 스킬의 링크를 못 지우면 알린다. 사용자가 다른 곳으로 건 링크는 지우지 않는다
        other = make_skill(os.path.join(tmp, "elsewhere"), "plain")
        ok, err = hud.modify_group("add", "k", "plain", "skill")
        assert ok, err
        ok, err = hud.modify_group("add", "h", "plain", "skill")
        assert ok, err
        ok, err = hud.modify_group("remove", "h", "plain", "skill")
        assert ok, err
        users = os.path.join(proj, ".agents", "skills", "plain")
        os.symlink(other, users)
        ok, err = hud.assign_set("h", proj)
        assert not ok and "plain" in err and "partly applied" in err, (ok, err)
        assert os.path.realpath(users) == other, "사용자의 링크를 지웠다"
        assert hud.collect_groups({"project_dir": proj})["assigned"] == "h", "적용된 상태를 기록하지 않았다"
        os.unlink(users)

        # 지워진 스킬이 그룹에 남아 있어도 다른 그룹 적용을 실패로 알리지 않는다
        shutil.rmtree(os.path.join(home, ".claude", "skills", "plain"))
        ok, err = hud.assign_set("h", proj)
        assert ok, err

        # 프로젝트마다 내용이 다른 같은 이름도 고를 수 있다
        a, b = os.path.join(tmp, "A"), os.path.join(tmp, "B")
        in_a = make_skill(os.path.join(a, ".agents", "skills"), "review", "from A")
        in_b = make_skill(os.path.join(b, ".agents", "skills"), "review", "from B")
        hud.known_projects = lambda: [proj, a, b]
        choices = hud.collect_groups({"project_dir": proj})["skill_choices"]
        assert sorted(c["source"] for c in choices["review"]) == sorted([in_a, in_b]), choices

        # 고정한 원본이 사라져 끊어진 링크도 다음 그룹의 원본으로 바꾼다
        gone = make_skill(os.path.join(tmp, "gone"), "fade", "old")
        fresh = make_skill(os.path.join(home, ".claude", "skills"), "fade", "new")
        hud.known_projects = lambda: [proj, os.path.join(tmp, "gone-project")]
        json.dump({"old": {"plugins": [], "skills": ["fade"], "sources": {"fade": gone}},
                   "new": {"plugins": [], "skills": ["fade"], "sources": {"fade": fresh}}}, open(hud.MODES_FILE, "w"))
        ok, err = hud.assign_set("old", proj)
        assert ok, err
        shutil.rmtree(gone)
        ok, err = hud.assign_set("new", proj)
        assert ok, err
        assert os.path.realpath(os.path.join(proj, ".agents", "skills", "fade")) == fresh, "끊어진 링크를 못 바꿨다"
        ok, err = hud.assign_set("", proj)
        assert ok, err

        # 다른 내용의 실제 폴더가 자리에 있으면 지우지 않고 알린다. 내용이 같으면 문제없다
        held = make_skill(os.path.join(proj, ".agents", "skills"), "fade", "hand made")
        json.dump({"new": {"plugins": [], "skills": ["fade"], "sources": {"fade": fresh}}}, open(hud.MODES_FILE, "w"))
        ok, err = hud.assign_set("new", proj)
        assert not ok and "fade" in err, "다른 파일이 읽히는데 성공으로 처리했다"
        assert not os.path.islink(held), "사용자 폴더를 바꿨다"
        shutil.copy(os.path.join(fresh, "SKILL.md"), os.path.join(held, "SKILL.md"))
        ok, err = hud.assign_set("new", proj)
        assert ok, err
        shutil.rmtree(held)
        hud.assign_set("", proj)

        # 옛 파일 형식도 읽는다
        json.dump({"old": ["p@m"], "older": {"plugins": [], "skills": ["same"]}}, open(hud.MODES_FILE, "w"))
        ok, err = hud.assign_set("older", proj)
        assert ok, err
        assert os.path.realpath(link) == from_plugin
        assert 'dataset.source' in hud.PAGE, "화면에서 파일을 고를 수 없다"
        assert "new_group_file_prompt" in hud.PAGE, "새 그룹의 첫 스킬은 파일을 고를 수 없다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
