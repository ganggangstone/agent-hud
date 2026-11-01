"""플러그인 스킬과 이름만 같은 스킬을 따로 보여 주는지 본다.
   Claude Code는 둘을 별개로 읽는다(센티널 실측: 플러그인을 켜면 `이름`과 `플러그인:이름`이 함께 보이고,
   skillOverrides는 플러그인 밖 쪽만 끄며, 플러그인을 꺼도 플러그인 밖 쪽은 남는다).
   내용까지 같은 복사본이나 링크는 지금처럼 플러그인 행에 합친다.
   python3 tests/test_same_name_skills.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def make_skill(root, name, desc="plugin copy"):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: {desc}\n---\n")
    return d


def rows(proj):
    state = hud.collect_skills({"project_dir": proj})
    plugin = {s["id"]: s for r in state["rows"] if r["name"] for s in r["skills"]}
    loose = {s["id"]: s for r in state["rows"] if not r["name"] for s in r["skills"]}
    return state["loaded"], plugin, loose


def set_plugin(proj, on):
    assert hud.set_plugins({"p@m": on}, proj)[0]


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    try:
        home = os.path.join(tmp, "home")
        os.environ.pop("CODEX_HOME", None)   # 켜져 있으면 Codex가 ~/.codex/skills를 안 읽는다
        hud.HOME = home
        hud.CLAUDE_DIR = os.path.join(home, ".claude")
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        hud.SETS_FILE = os.path.join(tmp, "sets.json")
        plug = os.path.join(tmp, "plug")
        make_skill(os.path.join(plug, "skills"), "same")
        origin = make_skill(os.path.join(plug, "skills"), "linked")
        os.makedirs(os.path.join(home, ".claude", "plugins"))
        json.dump({"plugins": {"p@m": [{"installPath": plug, "version": "1"}]}},
                  open(os.path.join(home, ".claude", "plugins", "installed_plugins.json"), "w"))
        make_skill(os.path.join(home, ".claude", "skills"), "same", desc="my own copy")   # 이름만 같다
        make_skill(os.path.join(home, ".codex", "skills"), "same")                        # 내용까지 같다
        proj = os.path.join(tmp, "proj"); os.makedirs(os.path.join(proj, ".agents", "skills"))
        os.symlink(origin, os.path.join(proj, ".agents", "skills", "linked"))
        hud.known_projects = lambda: [proj]

        # 플러그인을 꺼도 이름만 같은 전역 스킬은 읽히고, 자기 스위치를 가진다
        set_plugin(proj, False)
        loaded, plugin, loose = rows(proj)
        assert "same" in loose, "이름만 같은 스킬이 플러그인 행에 묻혔다"
        assert loose["same"]["desc"] == "my own copy", "다른 파일을 보여 준다"
        assert loose["same"]["enabled"] is True and "Claude Code" in loose["same"]["agents"]
        assert loaded == 1, f"꺼진 플러그인과 무관하게 읽히는 스킬을 못 셌다: {loaded}"
        assert not loose["same"]["linkable"], "체크박스가 이 파일 대신 플러그인 파일을 링크하게 된다"

        # 내용까지 같은 복사본과 링크는 플러그인 행에 합친다
        assert "Codex" in plugin["same"]["agents"], "같은 내용의 복사본을 플러그인 행에 합치지 못했다"
        assert "Antigravity" in plugin["linked"]["agents"], "링크한 플러그인 스킬의 에이전트를 잃었다"
        assert plugin["same"]["linkable"] and plugin["linked"]["linkable"]
        assert set(loose) == {"same"}, f"복사본이나 링크가 따로 나왔다: {sorted(loose)}"

        # 플러그인을 켜면 둘 다 읽힌다. 플러그인 폴더는 링크가 어디 걸려 있든 Claude Code가 읽는다
        set_plugin(proj, True)
        loaded, plugin, loose = rows(proj)
        assert "Claude Code" in plugin["same"]["agents"], "복사본 때문에 플러그인 스킬이 빠졌다"
        assert "Claude Code" in plugin["linked"]["agents"], "링크 때문에 플러그인 스킬이 빠졌다"
        assert loaded == 3, f"같은 이름 두 개와 링크된 스킬을 다 못 셌다: {loaded}"

        # 스위치는 플러그인 밖 쪽만 끈다
        ok, err = hud.set_skill_overrides({"same": False}, proj)
        assert ok, err
        loaded, plugin, loose = rows(proj)
        assert loose["same"]["enabled"] is False
        assert "Claude Code" in plugin["same"]["agents"]
        assert loaded == 2, f"끈 쪽만 빠져야 한다: {loaded}"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
