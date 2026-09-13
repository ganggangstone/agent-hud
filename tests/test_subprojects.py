"""자기 에이전트 설정을 가진 하위 폴더를 프로젝트로 찾아내는지 본다.
   python3 tests/test_subprojects.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def main():
    tmp = tempfile.mkdtemp()
    try:
        root = os.path.join(tmp, "proj"); os.makedirs(root)
        # 자기 .claude/skills 를 가진 하위 폴더
        os.makedirs(os.path.join(root, "app", ".claude", "skills", "s1"))
        open(os.path.join(root, "app", ".claude", "skills", "s1", "SKILL.md"), "w").write(
            "---\nname: s1\ndescription: x\n---\n")
        # 자기 설정만 가진 하위 폴더
        os.makedirs(os.path.join(root, "infra", ".claude"))
        open(os.path.join(root, "infra", ".claude", "settings.json"), "w").write("{}")
        # 지침만 있는 폴더는 프로젝트가 아니다
        os.makedirs(os.path.join(root, "docs"))
        open(os.path.join(root, "docs", "CLAUDE.md"), "w").write("x")
        # 가지치기 대상 안은 보지 않는다
        os.makedirs(os.path.join(root, "node_modules", "pkg", ".claude", "skills"))

        rows, truncated, subs = hud._scan_tree(root)
        subs = sorted(os.path.relpath(p, root) for p in subs)
        assert subs == ["app", "infra"], subs

        # 목록에 올라가고, 이미 있는 항목의 시각은 안 바뀐다
        hud.PROJECTS_FILE = os.path.join(tmp, "projects.json")
        json.dump({root: 1000.0}, open(hud.PROJECTS_FILE, "w"))
        hud.remember_project(os.path.join(root, "app"))
        hud.remember_project(root)
        got = json.load(open(hud.PROJECTS_FILE))
        assert os.path.join(root, "app") in got, "하위 프로젝트가 목록에 없다"
        assert got[root] == 1000.0, "이미 있는 프로젝트의 시각을 건드렸다"
        # 발견된 폴더는 하루 뒤로 놓는다 -- 오늘 직접 연 프로젝트가 목록에서 위에 오도록
        import time as _t
        assert got[os.path.join(root, "app")] <= _t.time() - 86000, "발견된 폴더가 뒤로 안 밀렸다"
        # 두 번 발견해도 시각이 안 바뀐다
        first = got[os.path.join(root, "app")]
        hud.remember_project(os.path.join(root, "app"))
        assert json.load(open(hud.PROJECTS_FILE))[os.path.join(root, "app")] == first, "다시 발견하니 시각이 바뀐다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
