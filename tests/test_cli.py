"""CLI가 서버 없이도 그룹을 적용하는지 본다.
   python3 tests/test_cli.py"""
import json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server.py")


def run(args, home, cwd=None):
    env = dict(os.environ, AGENT_HUD_HOME=home)
    return subprocess.run([sys.executable, SERVER] + args, capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=30)


def make_skill(root, name):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: x\n---\n")


def main():
    tmp = tempfile.mkdtemp()
    try:
        home = os.path.join(tmp, "hudhome"); os.makedirs(home)
        make_skill(os.path.join(tmp, "home", ".agents", "skills"), "vid-a")
        make_skill(os.path.join(tmp, "home", ".agents", "skills"), "dev-a")
        json.dump({"video": {"plugins": [], "skills": ["vid-a"]},
                   "dev": {"plugins": [], "skills": ["dev-a"]}},
                  open(os.path.join(home, "modes.json"), "w"))
        proj = os.path.join(tmp, "proj"); os.makedirs(proj)
        env_home = os.path.join(tmp, "home")

        # HOME을 옮겨 사용자 스킬 폴더를 가짜로 만든다
        os.environ["HOME"] = env_home

        r = run(["groups"], home, cwd=proj)
        assert r.returncode == 0, r.stderr
        assert "video" in r.stdout and "dev" in r.stdout, r.stdout
        assert "적용됨" not in r.stdout, "아직 적용 안 했는데 적용됐다고 한다"

        r = run(["apply", "video"], home, cwd=proj)
        assert r.returncode == 0, r.stderr + r.stdout
        for d in (".claude/skills", ".agents/skills"):
            p = os.path.join(proj, d, "vid-a")
            assert os.path.islink(p), f"{d}에 링크가 없다"
            assert not os.path.exists(os.path.join(proj, d, "dev-a")), "다른 그룹이 걸렸다"

        r = run(["groups"], home, cwd=proj)
        assert "적용됨" in r.stdout, "적용한 그룹을 표시하지 않는다"

        r = run(["apply", "--off"], home, cwd=proj)
        assert r.returncode == 0, r.stderr
        assert not os.path.exists(os.path.join(proj, ".claude/skills", "vid-a")), "해제가 안 됐다"

        r = run(["apply", "nope"], home, cwd=proj)
        assert r.returncode != 0 and "그런 그룹이 없습니다" in r.stderr, (r.returncode, r.stderr)

        r = run(["apply", "video", os.path.join(tmp, "nodir")], home)
        assert r.returncode != 0 and "폴더가 없습니다" in r.stderr, r.stderr

        r = run(["--help"], home)
        assert r.returncode == 0 and "agent-hud apply" in r.stdout
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
