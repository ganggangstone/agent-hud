"""Antigravity CLI(agy)가 읽는 스킬 폴더를 뱃지에 반영하는지 본다. 2026-09 센티널 실측(ADR 10):
   - 전역 ~/.gemini/config/skills 를 읽는다
   - 프로젝트 .agents/skills 를 읽는다(링크도 따라간다)
   - 전역 ~/.agents/skills 는 읽지 않는다
   python3 tests/test_skill_roots_agy.py"""
import importlib.util, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)

AGY = "Antigravity"


def skill(root, name):
    os.makedirs(os.path.join(root, name))
    with open(os.path.join(root, name, "SKILL.md"), "w") as f:
        f.write(f"---\nname: {name}\ndescription: test\n---\nbody\n")


def main():
    tmp = tempfile.mkdtemp()
    try:
        home = os.path.join(tmp, "home"); proj = os.path.join(tmp, "proj")
        skill(os.path.join(home, ".gemini", "config", "skills"), "agy-global")
        skill(os.path.join(home, ".agents", "skills"), "agents-global")
        skill(os.path.join(proj, ".agents", "skills"), "agents-project")
        hud.HOME = home

        assert AGY in hud.SKILL_AGENTS, "Antigravity가 에이전트 목록에 없다"
        index = hud._skill_root_index(proj)
        assert index["agy-global"]["agents"] == [AGY], index["agy-global"]
        assert AGY in index["agents-project"]["agents"], "프로젝트 .agents/skills를 agy가 읽는데 표시하지 않는다"
        assert AGY not in index["agents-global"]["agents"], "agy는 ~/.agents/skills를 읽지 않는다"

        # 원본 위치로도 잡혀서 그룹 링크의 원본이 될 수 있다
        assert "agy-global" in hud.skill_sources(proj), "~/.gemini/config/skills를 링크 원본으로 못 찾는다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
