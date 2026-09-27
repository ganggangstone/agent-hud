"""플러그인 밖 스킬을 프로젝트마다 켜고 끄는지 본다.
   Claude Code는 settings의 skillOverrides {"이름": "off"}로 사용자·프로젝트 스킬을 목록에서
   뺀다(직접 확인, ADR 10). 플러그인 스킬에는 듣지 않아서 스위치는 플러그인 밖 스킬에만 둔다.
   - 스위치: 끄면 로컬 설정에 "off", 켜면 키를 지운다. 공유 설정이 "off"면 로컬에 "on"을 쓴다.
   - 읽히는 스킬 수는 꺼진 스킬을 빼고 센다.
   - 그룹을 적용하면 그룹에 없는 플러그인 밖 스킬을 끈다. Claude Code가 안 읽는 스킬은 건드리지 않는다.
   python3 tests/test_skill_overrides.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def make_skill(root, name):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: x\n---\n")


def local(proj):
    p = os.path.join(proj, ".claude", "settings.local.json")
    return json.load(open(p)).get("skillOverrides", {}) if os.path.exists(p) else {}


def state(proj):
    s = hud.collect_skills({"project": proj})
    loose = {sk["name"]: sk for r in s["rows"] if r["enabled"] is None for sk in r["skills"]}
    return s["loaded"], loose


def main():
    tmp = tempfile.mkdtemp()
    try:
        home = os.path.join(tmp, "home")
        hud.HOME = home
        hud.CLAUDE_DIR = os.path.join(home, ".claude")
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        hud.SETS_FILE = os.path.join(tmp, "sets.json")
        hud.PROJECTS_FILE = os.path.join(tmp, "projects.json")
        hud.known_plugin_names = lambda: set()
        make_skill(os.path.join(home, ".claude", "skills"), "g-on")
        make_skill(os.path.join(home, ".claude", "skills"), "g-off")
        make_skill(os.path.join(home, ".agents", "skills"), "a-only")     # Claude Code는 안 읽는다
        proj = os.path.join(tmp, "proj")
        make_skill(os.path.join(proj, ".claude", "skills"), "p-local")
        hud.register_project(proj)

        n, loose = state(proj)
        assert n == 3, n                                        # g-on, g-off, p-local
        assert all(loose[n]["enabled"] for n in ("g-on", "g-off", "p-local")), loose
        assert "enabled" not in loose["a-only"], "Claude Code가 안 읽는 스킬에 스위치를 달았다"

        # 끄면 로컬에 "off", 수에서 빠진다
        ok, err = hud.set_skill_overrides({"g-off": False}, proj)
        assert ok, err
        assert local(proj) == {"g-off": "off"}, local(proj)
        n, loose = state(proj)
        assert n == 2 and not loose["g-off"]["enabled"], (n, loose["g-off"])

        # 켜면 키를 지운다
        hud.set_skill_overrides({"g-off": True}, proj)
        assert local(proj) == {}, local(proj)
        assert state(proj)[0] == 3

        # 공유 설정이 끄고 있으면 로컬에 "on"을 써서 이긴다
        shared = os.path.join(proj, ".claude", "settings.json")
        json.dump({"skillOverrides": {"p-local": "off"}}, open(shared, "w"))
        assert state(proj)[0] == 2
        hud.set_skill_overrides({"p-local": True}, proj)
        assert local(proj) == {"p-local": "on"}, local(proj)
        assert state(proj)[0] == 3
        os.remove(shared)

        # user-invocable-only 도 목록에서 빠진다(직접 확인). 수에서 뺀다
        json.dump({"skillOverrides": {"g-on": "user-invocable-only"}}, open(shared, "w"))
        assert state(proj)[0] == 2
        os.remove(shared)

        # 모르는 이름은 쓰지 않는다
        ok, err = hud.set_skill_overrides({"nope": False}, proj)
        assert not ok and "nope" in err, (ok, err)

        # 그룹 적용: 그룹에 없는 플러그인 밖 스킬은 끄고, 있는 것은 켠다
        json.dump({"app": {"plugins": [], "skills": ["g-on"]}}, open(hud.MODES_FILE, "w"))
        ok, err = hud.assign_set("app", proj)
        assert ok, err
        ov = local(proj)
        assert ov.get("g-off") == "off" and ov.get("p-local") == "off", ov
        assert ov.get("g-on") in (None, "on"), ov
        assert "a-only" not in ov, "Claude Code가 안 읽는 스킬까지 썼다"
        assert state(proj)[0] == 1, state(proj)[0]

        # 적용 해제는 플러그인처럼 스킬 설정도 그대로 둔다
        ok, err = hud.assign_set("", proj)
        assert ok, err
        assert local(proj) == ov, (local(proj), ov)
    finally:
        shutil.rmtree(tmp)
    print("ok")


if __name__ == "__main__":
    main()
