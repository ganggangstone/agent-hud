"""AGENT_HUD_HOME이 사용자 데이터 위치를 옮기는지 본다.
   패키지로 설치하면 코드 폴더가 업그레이드마다 갈리므로, 데이터가 거기 있으면 안 된다.
   python3 test_data_dir.py"""
import importlib.util, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "server.py")


def load(env_home):
    """별도 프로세스에서 import해 데이터 경로를 받아온다 (모듈 전역이라 재import가 필요)."""
    code = (
        "import importlib.util, json, sys;"
        f"spec=importlib.util.spec_from_file_location('hud', {SERVER!r});"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
        "print(json.dumps([m.TOOL_DIR, m.PROJECTS_FILE, m.MODES_FILE, m.SETS_FILE, m.PORT_FILE]))"
    )
    env = dict(os.environ)
    env.pop("AGENT_HUD_HOME", None)
    if env_home:
        env["AGENT_HUD_HOME"] = env_home
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    import json
    return json.loads(out.stdout.strip().splitlines()[-1])


def main():
    tmp = tempfile.mkdtemp()
    try:
        # 기본값: 스크립트 옆
        default = load(None)
        assert default[0] == HERE, f"기본 위치가 스크립트 옆이 아니다: {default[0]}"

        # 환경변수로 옮긴다
        moved = os.path.join(tmp, "data")
        got = load(moved)
        assert got[0] == moved, got[0]
        for path in got[1:]:
            assert path.startswith(moved + os.sep), f"데이터가 안 옮겨졌다: {path}"
        assert os.path.isdir(moved), "폴더를 만들지 않았다"

        # 없는 중간 경로도 만들어야 한다
        deep = os.path.join(tmp, "a", "b", "c")
        assert load(deep)[0] == deep and os.path.isdir(deep), "중간 경로를 못 만든다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
