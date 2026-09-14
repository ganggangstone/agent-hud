"""_loaded_count()가 실제로 로드되는 스킬만 세는지 본다.
   꺼진 플러그인의 스킬은 컨텍스트에 안 올라가므로 세지 않는다.
   permissions.deny로 차단한 스킬은 목록에 그대로 남는다(2026-09 센티널 실측, ADR 10).
   그래서 차단은 로드 수를 줄이지 않는다.
   python3 tests/test_loaded.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)

C = ["Claude Code"]
OTHERS = ["Codex", "Cursor"]


def sk(name, agents=C, blocked=False):
    return {"id": name, "agents": agents, "blocked": blocked}


def unit():
    rows = [
        {"name": "on@m", "enabled": True, "skills": [sk("a"), sk("b"), sk("c", blocked=True)]},
        {"name": "off@m", "enabled": False, "skills": [sk("d"), sk("e")]},
        # 플러그인 밖의 스킬: Claude Code가 보는 것만 센다
        {"name": "", "enabled": None, "skills": [sk("f"), sk("g", agents=OTHERS)]},
    ]
    got = hud._loaded_count(rows)
    assert got == 4, f"켜진 플러그인 3(차단 포함) + 단독 1 = 4여야 하는데 {got}"

    # 플러그인을 끄면 그만큼 준다
    rows[0]["enabled"] = False
    assert hud._loaded_count(rows) == 1, "꺼진 플러그인의 스킬을 세고 있다"

    # 다른 에이전트만 보는 스킬은 Claude Code 컨텍스트에 안 올라간다
    rows[0]["enabled"] = True
    rows[2]["skills"][0]["agents"] = OTHERS
    assert hud._loaded_count(rows) == 3, "Claude Code가 못 보는 스킬을 세고 있다"

    assert hud._loaded_count([]) == 0


def end_to_end():
    """화면에 나가는 값 그대로: 차단한 플러그인 스킬도 Claude Code 뱃지를 유지하고 로드 수에 들어간다."""
    tmp = tempfile.mkdtemp()
    try:
        home = os.path.join(tmp, "home"); claude = os.path.join(home, ".claude")
        plugin = os.path.join(tmp, "plugin")
        for s in ("s1", "s2"):
            os.makedirs(os.path.join(plugin, "skills", s))
            with open(os.path.join(plugin, "skills", s, "SKILL.md"), "w") as f:
                f.write(f"---\nname: {s}\ndescription: test skill {s}\n---\nbody\n")
        os.makedirs(os.path.join(claude, "plugins"))
        json.dump({"plugins": {"p@m": [{"installPath": plugin, "version": "1"}]}},
                  open(os.path.join(claude, "plugins", "installed_plugins.json"), "w"))
        proj = os.path.join(tmp, "proj"); os.makedirs(os.path.join(proj, ".claude"))
        json.dump({"enabledPlugins": {"p@m": True}, "permissions": {"deny": ["Skill(p@m:s1)"]}},
                  open(os.path.join(proj, ".claude", "settings.local.json"), "w"))

        hud.HOME, hud.CLAUDE_DIR = home, claude
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        hud.SETS_FILE = os.path.join(tmp, "project-sets.json")
        hud.PROJECTS_FILE = os.path.join(tmp, "projects.json")

        state = hud.collect_skills({"project_dir": proj})
        row = next(r for r in state["rows"] if r["name"] == "p@m")
        s1 = next(s for s in row["skills"] if s["id"] == "s1")
        assert s1["blocked"], "차단 표시가 사라졌다"
        assert "Claude Code" in s1["agents"], "차단했다고 Claude Code가 못 보는 것처럼 표시한다"
        assert state["loaded"] == 2, f"차단한 스킬도 로드되므로 2여야 하는데 {state['loaded']}"
    finally:
        shutil.rmtree(tmp)


def main():
    unit()
    end_to_end()
    print("PASS")


if __name__ == "__main__":
    main()
