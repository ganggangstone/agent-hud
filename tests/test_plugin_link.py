"""스킬 폴더에 링크한 플러그인 스킬을 측정대로 다루는지 본다(#40).
   Claude Code는 .claude/skills의 링크를 플러그인과 별개로 읽는다(센티널 실측: 꺼도 `이름`이 보이고, 켜면 `이름`과
   `플러그인:이름`이 함께 보이며, skillOverrides는 링크 쪽만 끈다). 공유 체크박스는 다른 에이전트를 위한 것이므로
   플러그인 스킬을 .agents/skills에만 건다. 그룹은 Claude Code에서도 쓰라는 뜻이므로 모든 폴더에 건다.
   python3 tests/test_plugin_link.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def make_skill(root, name):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: plugin skill\n---\n")
    return d


def state(proj):
    s = hud.collect_skills({"project_dir": proj})
    plugin = {x["id"]: x for r in s["rows"] if r["name"] for x in r["skills"]}
    loose = {x["id"]: x for r in s["rows"] if not r["name"] for x in r["skills"]}
    return s, plugin, loose


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
        src = make_skill(os.path.join(plug, "skills"), "ps")
        os.makedirs(os.path.join(home, ".claude", "plugins"))
        json.dump({"plugins": {"p@m": [{"installPath": plug, "version": "1"}]}},
                  open(os.path.join(home, ".claude", "plugins", "installed_plugins.json"), "w"))
        proj = os.path.join(tmp, "proj"); os.makedirs(proj)
        hud.PROJECT_DIR = proj
        hud.known_projects = lambda: [proj]
        claude_link = os.path.join(proj, ".claude", "skills", "ps")
        agents_link = os.path.join(proj, ".agents", "skills", "ps")
        assert hud.set_plugins({"p@m": False}, proj)[0]

        # 공유 체크박스는 Claude Code를 켜지 않는다
        ok, err = hud.link_skill("ps", True, proj)
        assert ok, err
        assert os.path.islink(agents_link) and not os.path.lexists(claude_link), "꺼 둔 플러그인 스킬을 Claude Code에 걸었다"
        assert hud.skill_is_shared(proj, "ps"), "다른 에이전트에 공유됐는데 꺼져 보인다"
        s, plugin, loose = state(proj)
        assert s["loaded"] == 0
        assert "Codex" in plugin["ps"]["agents"] and "ps" not in loose
        ok, err = hud.link_skill("ps", False, proj)
        assert ok, err
        assert not os.path.lexists(agents_link)

        # 끈 플러그인 + 링크: 읽힌다. 자기 스위치로 끈다
        os.makedirs(os.path.dirname(claude_link))
        os.symlink(src, claude_link)
        s, plugin, loose = state(proj)
        assert s["loaded"] == 1, f"링크로 읽히는 스킬을 못 셌다: {s['loaded']}"
        assert loose["ps"]["enabled"] is True and "Claude Code" in loose["ps"]["agents"]
        assert s["tokens"]["agents"]["Claude Code"]["skills"] == 1
        ok, err = hud.set_skill_overrides({"ps": False}, proj)
        assert ok, err
        s, plugin, loose = state(proj)
        assert s["loaded"] == 0 and loose["ps"]["enabled"] is False, "스위치로 꺼지지 않는다"
        ok, err = hud.set_skill_overrides({"ps": True}, proj)
        assert ok, err

        # 켠 플러그인 + 링크: 둘 다 읽힌다
        assert hud.set_plugins({"p@m": True}, proj)[0]
        s, plugin, loose = state(proj)
        assert s["loaded"] == 2, f"둘 다 세야 한다: {s['loaded']}"
        assert s["tokens"]["agents"]["Claude Code"]["skills"] == 2, s["tokens"]["agents"]["Claude Code"]
        ok, err = hud.set_skill_overrides({"ps": False}, proj)
        assert ok, err
        s, plugin, loose = state(proj)
        assert s["loaded"] == 1 and "Claude Code" in plugin["ps"]["agents"], "플러그인 쪽까지 꺼졌다"
        ok, err = hud.set_skill_overrides({"ps": True}, proj)
        assert ok, err
        os.unlink(claude_link)
        assert hud.set_plugins({"p@m": False}, proj)[0]

        # 그룹은 Claude Code에서도 쓰라는 뜻이다
        ok, err = hud.modify_group("add", "g", "ps", "skill")
        assert ok, err
        ok, err = hud.assign_set("g", proj)
        assert ok, err
        assert os.path.islink(claude_link) and os.path.islink(agents_link), "그룹이 모든 폴더에 걸지 않았다"
        s, plugin, loose = state(proj)
        assert loose["ps"]["enabled"] is True and s["loaded"] == 1
        ok, err = hud.assign_set("", proj)
        assert ok, err
        assert not os.path.lexists(claude_link) and not os.path.lexists(agents_link), "해제해도 링크가 남았다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
