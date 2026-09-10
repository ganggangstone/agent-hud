"""세트가 옛 modes.json을 그대로 읽는지, 프로젝트에 적용할 때 이 세트 스킬만 남기는지,
   그리고 어느 세트에도 없는 링크(사용자가 직접 건 것)는 건드리지 않는지 본다.
   python3 test_sets.py"""
import importlib.util, json, os, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("hud", os.path.join(HERE, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def make_skill(root, name):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: x\n---\n")
    return d


def main():
    tmp = tempfile.mkdtemp()
    try:
        home_skills = os.path.join(tmp, "home", ".agents", "skills")
        for n in ("vid-a", "dev-a", "loose-a"):
            make_skill(home_skills, n)
        hud.HOME = os.path.join(tmp, "home")
        hud.plugin_skills = lambda: {}
        hud.known_plugin_names = lambda: set()
        hud.toggle_plugin = lambda name, on: (True, "")
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        hud.SETS_FILE = os.path.join(tmp, "sets.json")
        proj = os.path.join(tmp, "proj"); os.makedirs(proj)

        # 옛 형식({이름: [플러그인]})도 읽혀야 한다
        json.dump({"legacy": ["p@m"]}, open(hud.MODES_FILE, "w"))
        assert hud.read_sets() == {"legacy": {"plugins": ["p@m"], "skills": []}}, hud.read_sets()

        json.dump({"video": {"plugins": [], "skills": ["vid-a"]},
                   "dev": {"plugins": [], "skills": ["dev-a"]}}, open(hud.MODES_FILE, "w"))

        # 사용자가 직접 건 링크 -- 어느 세트에도 없다
        hud.link_skill("loose-a", True, proj)
        assert hud.skill_is_shared(proj, "loose-a")

        ok, err = hud.assign_set("video", proj)
        assert ok, err
        assert hud.skill_is_shared(proj, "vid-a"), "세트 스킬이 안 걸렸다"
        assert not hud.skill_is_shared(proj, "dev-a"), "다른 세트 스킬이 걸렸다"
        assert hud.skill_is_shared(proj, "loose-a"), "세트 밖 링크를 건드렸다"
        assert json.load(open(hud.SETS_FILE))[proj] == "video"

        ok, err = hud.assign_set("dev", proj)
        assert ok, err
        assert hud.skill_is_shared(proj, "dev-a") and not hud.skill_is_shared(proj, "vid-a"), "세트 전환이 안 됐다"
        assert hud.skill_is_shared(proj, "loose-a"), "세트 밖 링크를 건드렸다"

        ok, err = hud.assign_set("", proj)
        assert ok, err
        assert not hud.skill_is_shared(proj, "dev-a"), "배정 해제가 안 됐다"
        assert hud.skill_is_shared(proj, "loose-a"), "해제가 세트 밖 링크까지 지웠다"
        assert proj not in json.load(open(hud.SETS_FILE))

        # 세트 편집
        ok, err = hud.modify_group("add", "video", "dev-a", "skill"); assert ok, err
        assert "dev-a" in hud.read_sets()["video"]["skills"]
        ok, err = hud.modify_group("remove", "video", "dev-a", "skill"); assert ok, err
        assert "dev-a" not in hud.read_sets()["video"]["skills"]
        ok, err = hud.modify_group("add", "video", "nope", "skill")
        assert not ok, "모르는 스킬을 그냥 넣었다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
