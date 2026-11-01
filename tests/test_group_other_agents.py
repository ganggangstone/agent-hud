"""Claude Code를 쓰지 않는 사용자에게 그룹이 어떻게 동작하는지 본다.
   - 바꿀 값이 없으면 .claude/settings.local.json을 만들지 않는다.
   - 그룹은 다른 에이전트의 스킬을 끄지 못하므로, 적용한 그룹에 그 에이전트가 계속 읽는 스킬을 알려 준다.
   - 플러그인이 없어도 스킬로 새 그룹을 만들 수 있다.
   python3 tests/test_group_other_agents.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def make_skill(root, name):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: x\n---\n")


def group(proj, name="g"):
    return [g for g in hud.collect_groups({"project_dir": proj})["groups"] if g["name"] == name][0]


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    try:
        os.environ.pop("CODEX_HOME", None)
        home = os.path.join(tmp, "home")
        hud.HOME = home
        hud.CLAUDE_DIR = os.path.join(home, ".claude")
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        hud.SETS_FILE = os.path.join(tmp, "sets.json")
        make_skill(os.path.join(home, ".agents", "skills"), "want")
        make_skill(os.path.join(home, ".agents", "skills"), "other")
        make_skill(os.path.join(home, ".agents", "skills"), "codex-off")
        proj = os.path.join(tmp, "proj"); os.makedirs(proj)
        hud.PROJECT_DIR = proj
        hud.known_projects = lambda: [proj]
        hud._codex_config = lambda: {"skills": {"config": [
            {"path": os.path.join(home, ".agents", "skills", "codex-off", "SKILL.md"), "enabled": False}]}}
        local = os.path.join(proj, ".claude", "settings.local.json")

        # 플러그인이 없어도 스킬로 그룹을 만든다
        ok, err = hud.modify_group("add", "g", "want", "skill")
        assert ok, err

        # 적용 전에는 안내하지 않는다
        assert not group(proj).get("still_visible"), "적용하지 않은 그룹에 안내가 나온다"

        ok, err = hud.assign_set("g", proj)
        assert ok, err
        assert not os.path.exists(local), "바꿀 값이 없는데 Claude 설정 파일을 만들었다"
        left = group(proj)["still_visible"]
        assert left["Codex"] == ["other"], f"Codex가 계속 읽는 스킬이 틀렸다: {left}"
        assert "codex-off" in left["Cursor"], "Codex 설정은 Cursor 표시를 바꾸지 않는다"
        assert "Claude Code" not in left, "Claude Code는 그룹이 끄므로 안내 대상이 아니다"

        ok, err = hud.assign_set("", proj)
        assert ok, err
        assert not os.path.exists(local), "해제하면서 Claude 설정 파일을 만들었다"
        assert not group(proj).get("still_visible"), "해제한 그룹에 안내가 남았다"

        # 이미 있는 설정 파일의 내용은 그대로 둔다
        os.makedirs(os.path.dirname(local), exist_ok=True)
        json.dump({"keep": 1}, open(local, "w"))
        ok, err = hud.assign_set("g", proj)
        assert ok, err
        assert json.load(open(local)) == {"keep": 1}, "관계없는 값을 바꿨다"

        page = hud.PAGE
        assert "editGroup('add', name.trim(), first.trim(), 'plugin')" not in page, "첫 항목을 플러그인으로만 받는다"
        assert "still_visible" in page, "화면이 안내를 그리지 않는다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
