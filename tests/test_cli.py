"""CLI가 서버 없이도 그룹을 적용하는지 본다.
   python3 tests/test_cli.py"""
import contextlib, importlib.util, io, json, os, shutil, stat, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server.py")


def run(args, home, cwd=None, extra_env=None, timeout=30):
    env = dict(os.environ, AGENT_HUD_HOME=home, **(extra_env or {}))
    return subprocess.run([sys.executable, SERVER] + args, capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=timeout)


def make_skill(root, name):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: x\n---\n")


def tokens_input_validation(tmp):
    """`tokens`는 `setup` 하나만 받는다. 잘못된 입력이면 서버가 뜨지 않고, 아무것도 만들지 않고 끝난다."""
    home = os.path.join(tmp, "tokhome"); os.makedirs(home)
    # 서버가 잘못 떠도 실제 대시보드(41717)에 붙지 않게 다른 포트를 준다
    quiet = {"AGENT_HUD_PORT": "41999", "AGENT_HUD_NO_BROWSER": "1"}
    for bad in ([ "tokens"], ["tokens", "nope"], ["tokens", "setup", "extra"]):
        try:
            r = run(bad, home, extra_env=quiet, timeout=10)
        except subprocess.TimeoutExpired:
            raise AssertionError(f"{bad}: 명령으로 처리하지 않고 서버가 떴다")
        assert r.returncode != 0, (bad, r.returncode)
        assert "agent-hud tokens setup" in r.stderr, (bad, r.stderr)
    leftovers = os.listdir(home)
    assert not any(n.startswith("tokenizer") for n in leftovers), f"잘못된 입력이 폴더를 만들었다: {leftovers}"


def tokens_setup_python_switch(tmp):
    """다른 파이썬으로 setup을 다시 돌리면 venv를 그 파이썬으로 다시 만든다. 진짜 설치 없이 명령만 본다:
    venv의 python 자리에 "파이썬 2.7"이라고 답하는 스텁을 두고, subprocess.run 은 기록만 하는 가짜로 바꾼다."""
    spec = importlib.util.spec_from_file_location("hud_cli", SERVER)
    hud = importlib.util.module_from_spec(spec); spec.loader.exec_module(hud)
    vdir = os.path.join(tmp, "swhome", "tokenizer-venv")
    hud.TOKENIZER_VENV, hud.TOKENIZER_CACHE = vdir, os.path.join(tmp, "swhome", "tokenizer-cache")
    real = hud.subprocess.run
    calls = []

    def fake(cmd, *a, **k):
        if cmd[0] == sys.executable or cmd[1:2] == ["-m"]:      # venv 만들기, pip: 기록만 한다
            calls.append((cmd, k.get("timeout")))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real(cmd, *a, **k)                               # 버전 물어보기와 스텁 실행은 진짜로

    def setup(version="2 7"):
        os.makedirs(os.path.join(vdir, "bin"), exist_ok=True)
        open(os.path.join(vdir, "pyvenv.cfg"), "w").write("home = /nowhere\n")
        py = os.path.join(vdir, "bin", "python")
        open(py, "w").write(f"#!/bin/sh\necho {version}\n"); os.chmod(py, 0o755)
        calls.clear()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = hud.cli_tokens(["setup"])
        return rc, err.getvalue()

    hud.subprocess.run = fake
    try:
        rc, err = setup("2 7")                                   # 다른 버전이 만든 venv
        venv_calls = [c for c, _ in calls if c[1:3] == ["-m", "venv"]]
        assert venv_calls == [[sys.executable, "-m", "venv", "--clear", vdir]], (venv_calls, err)
        assert all(t for _, t in calls), f"시간 제한 없는 호출: {calls}"
        rc, err = setup("%d %d" % sys.version_info[:2])          # 같은 버전이면 건드리지 않는다
        assert not [c for c, _ in calls if c[1:3] == ["-m", "venv"]], calls
        assert any("pip" in c for c, _ in calls)

        # 시간 안에 안 끝나는 pip: 멈춰 있지 않고 0이 아닌 값으로 끝나며 이유를 말한다
        def hang(cmd, *a, **k):
            if cmd[1:3] == ["-m", "pip"]:
                raise subprocess.TimeoutExpired(cmd, k.get("timeout"))
            return fake(cmd, *a, **k)
        hud.subprocess.run = hang
        rc, err = setup("%d %d" % sys.version_info[:2])
        assert rc == 1 and "Installing" in err and "tokenizer" in err, (rc, err)
        hud.subprocess.run = fake

        # venv 자리에 다른 내용물이 있으면 지우지 않고 알린다
        shutil.rmtree(vdir)
        os.makedirs(vdir); keep = os.path.join(vdir, "mine.txt"); open(keep, "w").write("x")
        calls.clear()
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = hud.cli_tokens(["setup"])
        assert rc == 1 and "not a tokenizer venv" in err.getvalue() and os.path.exists(keep) and not calls, (rc, err.getvalue(), calls)
    finally:
        hud.subprocess.run = real


def tokens_setup(tmp):
    """setup은 실패하면 0이 아닌 값으로 끝나고 이유를 말한다. 이미 돼 있으면 다시 돌려도 된다.
    진짜 설치(PyPI·어휘 내려받기)는 AGENT_HUD_TEST_TOKENIZER_HOME 이 가리키는 폴더에서 한 번만 한다
    -- CI는 테스트 앞 단계에서 같은 폴더에 setup을 돌려 둔다."""
    broken = os.path.join(tmp, "brokenhome"); os.makedirs(broken)
    open(os.path.join(broken, "tokenizer-venv"), "w").write("a file where the venv should go")
    r = run(["tokens", "setup"], broken, timeout=60)
    assert r.returncode == 1 and "tokenizer" in r.stderr, (r.returncode, r.stdout, r.stderr)

    shared = os.environ.get("AGENT_HUD_TEST_TOKENIZER_HOME")
    if not shared:
        assert not os.environ.get("CI"), "CI에서는 AGENT_HUD_TEST_TOKENIZER_HOME 이 있어야 한다"
        print("SKIP real tokens setup (AGENT_HUD_TEST_TOKENIZER_HOME 없음)")
        return
    r = run(["tokens", "setup"], shared, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "o200k_base" in r.stdout and "hello world" in r.stdout, r.stdout
    assert os.path.exists(os.path.join(shared, "tokenizer-venv", "bin", "python"))
    assert os.listdir(os.path.join(shared, "tokenizer-cache")), "어휘 파일이 캐시에 없다"


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
        assert "agent-hud tokens setup" in r.stdout, "도움말에 토큰 설정 명령이 없다"

        tokens_input_validation(tmp)
        tokens_setup_python_switch(tmp)
        tokens_setup(tmp)
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
