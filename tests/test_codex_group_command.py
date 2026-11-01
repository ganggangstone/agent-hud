"""적용한 그룹에 Codex 실행 명령을 주는지 본다. Codex 0.166 측정: 프로젝트 config.toml의 skills.config는 전역 스킬을
   끄지 못하고, 실행할 때 -c로 주면 그 실행에서만 꺼진다.
   python3 tests/test_codex_group_command.py"""
import importlib.util, json, os, shlex, shutil, tempfile, tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def make_skill(root, name, extra=""):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: x\n---\n{extra}")
    return os.path.realpath(os.path.join(d, "SKILL.md"))


def command(proj, name="g"):
    return [g for g in hud.collect_groups({"project_dir": proj})["groups"] if g["name"] == name][0].get("codex_command")


def entries(cmd):
    """셸이 나눈 대로 읽어 [(경로, enabled)]를 돌려준다."""
    args = shlex.split(cmd)
    assert args[args.index("&&") + 1:args.index("&&") + 3] == ["codex", "-c"], cmd
    data = tomllib.loads(args[-1])
    return args[1], [(e["path"], e["enabled"]) for e in data["skills"]["config"]]


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    try:
        os.environ.pop("CODEX_HOME", None)
        home = os.path.join(tmp, "ho me")   # 공백이 있어도 명령이 깨지면 안 된다
        hud.HOME = home
        hud.CLAUDE_DIR = os.path.join(home, ".claude")
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        hud.SETS_FILE = os.path.join(tmp, "sets.json")
        agents = os.path.join(home, ".agents", "skills")
        make_skill(agents, "want")
        other = make_skill(agents, "other")
        already = make_skill(agents, "already-off")
        cursor_only = make_skill(os.path.join(home, ".cursor", "skills"), "cursor-only")
        proj = os.path.join(tmp, "pro'j"); os.makedirs(proj)
        hud.PROJECT_DIR = proj
        hud.known_projects = lambda: [proj]
        hud._codex_config = lambda: {"skills": {"config": [{"path": already, "enabled": False}]}}

        ok, err = hud.modify_group("add", "g", "want", "skill")
        assert ok, err
        assert not command(proj), "적용하지 않은 그룹에 명령을 줬다"

        ok, err = hud.assign_set("g", proj)
        assert ok, err
        cwd, got = entries(command(proj))
        assert cwd == proj, f"프로젝트로 이동하지 않는다: {cwd}"
        assert (other, False) in got, f"그룹 밖 스킬을 끄지 않는다: {got}"
        assert (already, False) in got, "-c는 사용자 설정의 목록을 대신하므로 이미 끈 항목도 넣어야 한다"
        assert not any(p.endswith(os.path.join("want", "SKILL.md")) for p, _ in got), "그룹 스킬을 껐다"
        assert cursor_only not in [p for p, _ in got], "Codex가 읽지 않는 스킬을 넣었다"

        # 이름만 같은 다른 파일은 그룹 것이 아니므로 끈다
        twin = make_skill(os.path.join(proj, ".codex", "skills"), "want", "다른 내용\n")   # .agents/skills에는 그룹 링크가 있다
        json.dump({"g": {"plugins": [], "skills": ["want"], "sources": {"want": os.path.join(agents, "want")}}},
                  open(hud.MODES_FILE, "w"))
        _, got = entries(command(proj))
        assert (twin, False) in got, f"같은 이름의 다른 파일을 끄지 않는다: {got}"
        shutil.rmtree(os.path.join(proj, ".codex"))

        # 다른 에이전트 폴더에 같은 내용의 복사본이 먼저 있어도 Codex가 읽는 파일을 끈다
        make_skill(os.path.join(home, ".cursor", "skills"), "copied")
        copied = make_skill(os.path.join(home, ".agents", "skills"), "copied")
        _, got = entries(command(proj))
        assert (copied, False) in got, f"Cursor 복사본만 끄고 Codex가 읽는 파일을 놓쳤다: {got}"
        shutil.rmtree(os.path.join(home, ".agents", "skills", "copied"))
        shutil.rmtree(os.path.join(home, ".cursor", "skills", "copied"))

        # 스킬 폴더 자체가 링크면 두 경로를 다 끈다
        linked = make_skill(os.path.join(tmp, "elsewhere"), "linked")
        os.makedirs(os.path.join(home, ".codex"))
        os.symlink(os.path.join(tmp, "elsewhere"), os.path.join(home, ".codex", "skills"))
        _, got = entries(command(proj))
        assert (linked, False) in got and (os.path.join(home, ".codex", "skills", "linked", "SKILL.md"), False) in got, got
        os.unlink(os.path.join(home, ".codex", "skills"))

        # Codex 플러그인과 내장 스킬도 끈다
        plugin = make_skill(os.path.join(home, ".codex", "plugins", "cache", "m", "p", "1", "skills"), "plug")
        builtin = make_skill(os.path.join(home, ".codex", "skills", ".system"), "made-in")
        _, got = entries(command(proj))
        assert (plugin, False) in got, f"Codex 플러그인 스킬을 끄지 않는다: {got}"
        assert (builtin, False) in got, f"Codex 내장 스킬을 끄지 않는다: {got}"
        shutil.rmtree(os.path.join(home, ".codex"))

        # 그룹 밖에 Codex가 읽는 스킬이 없으면 명령도 없다
        shutil.rmtree(os.path.join(agents, "other"))
        shutil.rmtree(os.path.join(agents, "already-off"))
        assert not command(proj), "끌 것이 없는데 명령을 줬다"

        assert "codex_command" in hud.PAGE, "화면이 명령을 보여 주지 않는다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
