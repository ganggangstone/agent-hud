"""Codex 플러그인과 내장 스킬을 Codex 집계에 넣는지 본다. Codex 0.166 측정: 플러그인 캐시와 skills/.system을 읽고,
   allow_implicit_invocation: false인 스킬은 목록에 없으며, 플러그인 스킬은 플러그인:이름으로 보인다.
   python3 tests/test_codex_bundled_skills.py"""
import importlib.util, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def make_skill(root, folder, name=None, hidden=False):
    d = os.path.join(root, folder)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name or folder}\ndescription: x\n---\n")
    if hidden:
        os.makedirs(os.path.join(d, "agents"))
        open(os.path.join(d, "agents", "openai.yaml"), "w").write("policy:\n  allow_implicit_invocation: false\n")


def codex_names(proj):
    state = hud.collect_skills({"project_dir": proj})
    return state, {s["id"] for r in state["rows"] for s in r["skills"] if "Codex" in s["agents"]}


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    try:
        os.environ.pop("CODEX_HOME", None)
        home = os.path.join(tmp, "home")
        hud.HOME = home
        hud.CLAUDE_DIR = os.path.join(home, ".claude")
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        hud.SETS_FILE = os.path.join(tmp, "sets.json")
        proj = os.path.join(tmp, "proj"); os.makedirs(proj)
        hud.PROJECT_DIR = proj
        hud.known_projects = lambda: [proj]
        hud._codex_config = lambda: {}
        codex = os.path.join(home, ".codex")
        make_skill(os.path.join(codex, "skills", ".system"), "built-in")
        make_skill(os.path.join(codex, "skills", ".system"), "hidden-built-in", hidden=True)
        cache = os.path.join(codex, "plugins", "cache", "m")
        old = os.path.join(cache, "p", "1", "skills")
        new = os.path.join(cache, "p", "2", "skills")
        make_skill(old, "gone")
        make_skill(new, "setup", name="p-setup")     # 폴더 이름과 달라도 된다
        make_skill(new, "template", hidden=True)
        os.utime(os.path.join(cache, "p", "1"), (1, 1))
        make_skill(os.path.join(cache, "off", "1", "skills"), "off-skill")

        state, names = codex_names(proj)
        assert "built-in" in names, f"내장 스킬이 빠졌다: {names}"
        assert "p:p-setup" in names, f"플러그인 스킬을 플러그인:이름으로 세지 않는다: {names}"
        assert "hidden-built-in" not in names and "p:template" not in names, f"목록에 없는 스킬을 셌다: {names}"
        assert "p:gone" not in names, f"이전 버전을 셌다: {names}"
        assert state["tokens"]["agents"]["Codex"]["skills"] == len(names), "요약 숫자가 행과 다르다"

        rows = {s["id"]: s for r in state["rows"] for s in r["skills"]}
        assert rows["p:p-setup"]["agents"] == ["Codex"], "다른 에이전트도 읽는 것처럼 보인다"
        assert not rows["p:p-setup"]["issues"], f"폴더 이름이 달라도 문제가 아니다: {rows['p:p-setup']['issues']}"
        assert not rows["p:p-setup"]["linkable"], "Codex 플러그인 스킬은 공유 대상이 아니다"

        # 설정에서 끈 플러그인은 세지 않는다
        hud._codex_config = lambda: {"plugins": {"off@m": {"enabled": False}}}
        assert "off:off-skill" not in codex_names(proj)[1], "끈 플러그인을 셌다"
        open(os.path.join(cache, "off", ".codex-remote-plugin-install.json"), "w").write("{}")
        assert "off:off-skill" in codex_names(proj)[1], "원격 설치 플러그인은 설정으로 꺼지지 않는다"

        # CODEX_HOME을 쓰면 그쪽만 읽는다
        other = os.path.join(tmp, "other-codex")
        make_skill(os.path.join(other, "skills", ".system"), "other-built-in")
        os.environ["CODEX_HOME"] = other
        names = codex_names(proj)[1]
        assert "other-built-in" in names and "built-in" not in names, f"CODEX_HOME을 따르지 않는다: {names}"
        del os.environ["CODEX_HOME"]
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
