"""스킬을 어느 폴더로 공유할지 프로젝트마다 정하는 설정을 본다.
   설정이 없으면 ~/.claude가 있을 때만 .claude/skills를 관리한다. 프로젝트에 커밋된 .claude/는 동의로 보지 않는다.
   관리하지 않는 폴더에는 링크도 Claude 설정도 쓰지 않고 공유 판정에서도 뺀다. 있는 파일을 읽는 것은 그대로다.
   python3 tests/test_link_dirs.py"""
import importlib.util, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)

CLAUDE, AGENTS = ".claude/skills", ".agents/skills"


def make_skill(root, name):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: x\n---\n")
    return d


def rows(proj):
    return {s["id"]: s for r in hud.collect_skills({"project_dir": proj})["rows"] for s in r["skills"]}


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
        make_skill(os.path.join(home, ".agents", "skills"), "global")
        proj = os.path.join(tmp, "proj"); os.makedirs(proj)
        own = make_skill(os.path.join(proj, ".agents", "skills"), "own")
        hud.PROJECT_DIR = proj
        hud.known_projects = lambda: [proj]
        local = os.path.join(proj, ".claude", "settings.local.json")

        # ~/.claude가 없으면 .agents/skills만 관리한다
        assert hud.link_dirs(proj) == [AGENTS]
        assert hud.skill_is_shared(proj, "own"), "모든 에이전트가 보는 스킬이 공유 안 됨으로 나온다"
        state = rows(proj)
        assert state["own"]["missing"] == [], f"쓰지 않는 Claude Code를 빠졌다고 표시한다: {state['own']['missing']}"
        ok, err = hud.link_skill("global", True, proj)
        assert ok, err
        assert os.path.islink(os.path.join(proj, ".agents", "skills", "global"))
        assert not os.path.exists(os.path.join(proj, ".claude")), "관리하지 않는 Claude 폴더를 만들었다"
        assert hud.skill_is_shared(proj, "global")

        # 그룹도 같다
        ok, err = hud.modify_group("add", "g", "global", "skill")
        assert ok, err
        ok, err = hud.assign_set("g", proj)
        assert ok, err
        assert not os.path.exists(os.path.join(proj, ".claude")), "그룹이 Claude 폴더를 만들었다"
        ok, err = hud.assign_set("", proj)
        assert ok, err
        assert not os.path.lexists(os.path.join(proj, ".agents", "skills", "global")), "해제해도 링크가 남았다"

        # 커밋된 .claude/는 동의가 아니다. 읽히는 것은 표시하되 설정을 쓰지 않는다
        make_skill(os.path.join(proj, ".claude", "skills"), "committed")
        assert hud.link_dirs(proj) == [AGENTS]
        assert "Claude Code" in rows(proj)["committed"]["agents"], "있는 파일의 관측이 사라졌다"
        ok, err = hud.assign_set("g", proj)
        assert ok, err
        assert not os.path.exists(local), "관리하지 않는 Claude 설정을 썼다"
        ok, err = hud.assign_set("", proj)
        assert ok, err
        shutil.rmtree(os.path.join(proj, ".claude"))

        # 사용자가 켠 값이 기본값을 이긴다. 끈 폴더의 기존 링크도 끌 때는 지운다
        ok, err = hud.set_link_dirs(proj, [CLAUDE, AGENTS])
        assert ok, err
        assert hud.link_dirs(proj) == [CLAUDE, AGENTS]
        ok, err = hud.link_skill("global", True, proj)
        assert ok, err
        claude_link = os.path.join(proj, ".claude", "skills", "global")
        assert os.path.islink(claude_link)
        ok, err = hud.set_link_dirs(proj, [AGENTS])
        assert ok, err
        assert os.path.islink(claude_link), "설정만 바꿨는데 링크를 지웠다"
        ok, err = hud.link_skill("global", False, proj)
        assert ok, err
        assert not os.path.lexists(claude_link), "끈 폴더의 링크가 남았다"

        # Claude Code만 쓰는 경우
        only = os.path.join(tmp, "only"); os.makedirs(only)
        ok, err = hud.set_link_dirs(only, [CLAUDE])
        assert ok, err
        ok, err = hud.link_skill("global", True, only)
        assert ok, err
        assert not os.path.exists(os.path.join(only, ".agents")), "관리하지 않는 .agents를 만들었다"

        # 잘못된 값은 받지 않는다
        assert not hud.set_link_dirs(proj, [])[0]
        assert not hud.set_link_dirs(proj, ["../escape"])[0]

        # ~/.claude가 있으면 기본은 둘 다, 화면에 현재 값을 준다
        other = os.path.join(tmp, "other"); os.makedirs(other)
        panel = hud.collect_skills({"project_dir": other})["link_dirs"]
        assert [(d["dir"], d["on"]) for d in panel] == [(CLAUDE, False), (AGENTS, True)]
        assert hud.collect_skills({"project_dir": other})["link_dirs_auto_off"], "기본값으로 껐다는 안내가 없다"
        os.makedirs(hud.CLAUDE_DIR)
        assert hud.link_dirs(other) == [CLAUDE, AGENTS]
        assert not hud.collect_skills({"project_dir": other})["link_dirs_auto_off"]
        assert "/api/linkdirs" in hud.PAGE
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
