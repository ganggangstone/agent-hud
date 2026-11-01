"""Codex는 이름이 같아도 내용이 다른 스킬을 모두 읽는다(0.166 센티널 실측: 프로젝트 .agents/skills·.codex/skills,
   ~/.agents/skills, $CODEX_HOME/skills). Antigravity는 프로젝트 쪽만 읽는다(실측). 그대로 표시하고 세는지 본다.
   python3 tests/test_same_name_codex.py"""
import importlib.util, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def make_skill(root, name, desc):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: {desc}\n---\n")


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    try:
        home = os.path.join(tmp, "home")
        codex_home = os.path.join(tmp, "codex-home")
        os.environ["CODEX_HOME"] = codex_home
        hud.HOME = home
        hud.CLAUDE_DIR = os.path.join(home, ".claude")
        proj = os.path.join(tmp, "proj"); os.makedirs(proj)
        make_skill(os.path.join(proj, ".agents", "skills"), "dup", "project")
        make_skill(os.path.join(proj, ".codex", "skills"), "dup", "project codex")
        make_skill(os.path.join(home, ".agents", "skills"), "dup", "home")
        make_skill(os.path.join(codex_home, "skills"), "dup", "codex home")
        make_skill(os.path.join(home, ".gemini", "config", "skills"), "dup", "agy global")

        state = hud.collect_skills({"project_dir": proj})
        rows = {s["desc"]: s["agents"] for r in state["rows"] for s in r["skills"]}
        for desc in ("project", "project codex", "home", "codex home"):
            assert "Codex" in rows[desc], f"Codex가 읽는 {desc} 복사본을 못 본다고 표시한다: {rows}"
        assert "Codex" not in rows["agy global"]
        assert "Antigravity" in rows["project"] and "Antigravity" not in rows["agy global"], rows
        assert state["tokens"]["agents"]["Codex"]["skills"] == 4, state["tokens"]["agents"]
        assert state["tokens"]["agents"]["Antigravity"]["skills"] == 1, state["tokens"]["agents"]
        print("PASS")
    finally:
        os.environ.pop("CODEX_HOME", None)
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
