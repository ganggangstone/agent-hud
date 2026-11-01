"""Claude Code 없이 쓰다가 설치한 프로젝트에 빠진 링크를 안내하고 연결하는지 본다(#41).
   자동으로 연결하지 않는다. 처음부터 Claude Code가 있던 프로젝트와 폴더를 직접 고른 프로젝트에는 안내하지 않는다.
   python3 tests/test_claude_connect.py"""
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


def notice(proj):
    return hud.collect_skills({"project_dir": proj})["claude_connect"]


def new_project(tmp, name):
    proj = os.path.join(tmp, name)
    make_skill(os.path.join(proj, ".agents", "skills"), "own-" + name)
    return proj


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
        proj, kept, grouped, empty = (new_project(tmp, n) for n in ("proj", "kept", "grouped", "empty"))
        shutil.rmtree(os.path.join(empty, ".agents"))
        hud.PROJECT_DIR = proj
        hud.known_projects = lambda: [proj, kept, grouped, empty]
        assert hud.link_skill("global", True, proj)[0]
        assert hud.link_skill("global", True, kept)[0]
        assert hud.modify_group("add", "g", "global", "skill")[0]
        assert hud.assign_set("g", grouped)[0]

        # Claude Code가 없을 때는 안내하지 않는다. 프로젝트를 본 사실만 기억한다
        for p in (proj, kept, grouped, empty):
            assert notice(p) is None

        os.makedirs(hud.CLAUDE_DIR)

        # 설치 후: 빠진 것을 알려 주되 아직 만들지 않는다
        got = notice(proj)
        assert got == {"names": ["global", "own-proj"], "group": ""}, got
        assert not os.path.exists(os.path.join(proj, ".claude")), "묻지 않고 연결했다"

        # 연결
        ok, err = hud.connect_claude(proj)
        assert ok, err
        assert os.path.realpath(os.path.join(proj, ".claude", "skills", "own-proj")) == os.path.realpath(
            os.path.join(proj, ".agents", "skills", "own-proj")), "프로젝트 스킬을 못 걸었다"
        assert os.path.islink(os.path.join(proj, ".claude", "skills", "global"))
        assert hud.skill_is_shared(proj, "global")
        assert notice(proj) is None, "연결한 뒤에도 안내가 남았다"

        # 그대로 두기: 폴더를 고른 것으로 기록하고 다시 묻지 않는다
        assert notice(kept)["names"] == ["global", "own-kept"]
        ok, err = hud.connect_claude(kept, keep=True)
        assert ok, err
        assert hud.link_dirs(kept) == [".agents/skills"]
        assert notice(kept) is None
        assert not os.path.exists(os.path.join(kept, ".claude"))

        # 그룹을 적용한 프로젝트는 그룹을 다시 적용한다
        assert notice(grouped)["group"] == "g"
        ok, err = hud.connect_claude(grouped)
        assert ok, err
        assert os.path.islink(os.path.join(grouped, ".claude", "skills", "global")), "그룹을 다시 적용하지 않았다"
        assert notice(grouped) is None

        # 빠진 것이 없으면 안내하지 않고, 나중에 .agents에만 걸어도 다시 묻지 않는다
        assert notice(empty) is None
        make_skill(os.path.join(empty, ".agents", "skills"), "later")
        assert notice(empty) is None, "이미 끝난 전환을 다시 묻는다"

        # 처음부터 Claude Code가 있던 프로젝트는 묻지 않는다
        always = new_project(tmp, "always")
        hud.known_projects = lambda: [always]
        assert notice(always) is None

        # 폴더를 직접 고르면 묻지 않는다
        shutil.rmtree(hud.CLAUDE_DIR)
        chosen = new_project(tmp, "chosen")
        hud.known_projects = lambda: [chosen]
        assert notice(chosen) is None
        assert hud.set_link_dirs(chosen, [".claude/skills", ".agents/skills"])[0]
        os.makedirs(hud.CLAUDE_DIR)
        assert notice(chosen) is None, "직접 고른 프로젝트에 안내했다"
        assert "/api/claudeconnect" in hud.PAGE
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
