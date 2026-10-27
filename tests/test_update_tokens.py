"""「지금 업데이트」 뒤에 토큰 세기 도구를 같이 준비하는지 본다.
   - 준비돼 있지 않으면 새 설치본의 `agent-hud tokens setup`을 부른 뒤 다시 뜬다.
   - 이미 준비돼 있으면 부르지 않는다.
   - setup이 실패해도 다시 뜨는 것은 막지 않는다.
   python3 tests/test_update_tokens.py"""
import importlib.util, os, shutil, subprocess, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def main():
    tmp = tempfile.mkdtemp()
    calls, execs = [], []
    real_run, real_exec, real_sleep = hud.subprocess.run, hud.os.execv, hud.time.sleep
    hud.time.sleep = lambda s: None
    hud.os.execv = lambda exe, argv: execs.append(argv)
    try:
        prefix = os.path.join(tmp, "brew")
        hud.TOKENIZER_VENV = os.path.join(tmp, "tokenizer-venv")

        def run_ok(cmd, **k):
            calls.append(cmd); return subprocess.CompletedProcess(cmd, 0, "", "")
        hud.subprocess.run = run_ok

        # 1. 준비 안 됨 -> setup을 부르고 다시 뜬다
        hud.restart_into(prefix)
        assert calls == [[os.path.join(prefix, "bin", "agent-hud"), "tokens", "setup"]], calls
        assert execs == [[os.path.join(prefix, "bin", "agent-hud")]], execs

        # 2. 실패해도 다시 뜬다
        calls.clear(); execs.clear()
        def run_fail(cmd, **k):
            calls.append(cmd); raise subprocess.TimeoutExpired(cmd, 1)
        hud.subprocess.run = run_fail
        hud.restart_into(prefix)
        assert len(calls) == 1 and len(execs) == 1, (calls, execs)

        # 3. 이미 준비됨 -> 부르지 않는다
        calls.clear(); execs.clear()
        os.makedirs(os.path.join(hud.TOKENIZER_VENV, "bin"))
        py = os.path.join(hud.TOKENIZER_VENV, "bin", "python")
        open(py, "w").write("#!/bin/sh\n"); os.chmod(py, 0o755)
        hud.subprocess.run = run_ok
        hud.restart_into(prefix)
        assert calls == [] and len(execs) == 1, (calls, execs)
    finally:
        hud.subprocess.run, hud.os.execv, hud.time.sleep = real_run, real_exec, real_sleep
        shutil.rmtree(tmp)
    print("PASS")


if __name__ == "__main__":
    main()
