"""에이전트별로 세션 시작 때 읽는 지침과 스킬이 측정·문서와 맞는지 본다.
   python3 tests/test_agent_instructions.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def w(path, text="x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)
    return path


def env():
    tmp = os.path.realpath(tempfile.mkdtemp())
    hud.HOME = os.path.join(tmp, "home"); hud.CLAUDE_DIR = os.path.join(hud.HOME, ".claude")
    os.environ.pop("CODEX_HOME", None)
    return tmp

def test_plugin_row_group_chip_both_formats():
    tmp = env()
    try:
        d = os.path.join(hud.CLAUDE_DIR, "plugins"); ip = os.path.join(tmp, "pl")
        os.makedirs(os.path.join(ip, "skills"))
        w(os.path.join(d, "installed_plugins.json"), json.dumps({"plugins": {"p@m": [{"installPath": ip, "version": "1"}]}}))
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        for fmt in ({"g": ["p@m"]}, {"g": {"plugins": ["p@m"], "skills": []}}):
            json.dump(fmt, open(hud.MODES_FILE, "w"))
            row = [r for r in hud.collect_skills({"project_dir": tmp})["rows"] if r["name"] == "p@m"][0]
            assert row["modes"] == ["g"], (fmt, row["modes"])
    finally:
        shutil.rmtree(tmp)


#TESTS

if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
    print("PASS")
