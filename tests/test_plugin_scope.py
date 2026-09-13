"""플러그인 on/off가 프로젝트 단위인지 본다. 사용자 전역 파일은 절대 건드리면 안 된다.
   python3 tests/test_plugin_scope.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def main():
    tmp = tempfile.mkdtemp()
    try:
        home = os.path.join(tmp, "home", ".claude")
        os.makedirs(home)
        user_settings = os.path.join(home, "settings.json")
        json.dump({"enabledPlugins": {"a@m": True, "b@m": False}}, open(user_settings, "w"))
        before = open(user_settings).read()
        hud.CLAUDE_DIR = home
        hud.known_plugin_names = lambda: {"a@m", "b@m"}
        proj = os.path.join(tmp, "proj"); os.makedirs(proj)

        state, local = hud.plugin_state(proj)
        assert state == {"a@m": True, "b@m": False} and not local, (state, local)

        ok, err = hud.set_plugins({"a@m": False, "b@m": True}, proj)
        assert ok, err
        state, local = hud.plugin_state(proj)
        assert state == {"a@m": False, "b@m": True}, state
        assert local, "프로젝트가 직접 정했는데 아니라고 한다"

        # 다른 프로젝트는 영향을 안 받는다
        other = os.path.join(tmp, "other"); os.makedirs(other)
        assert hud.plugin_state(other)[0] == {"a@m": True, "b@m": False}, "다른 프로젝트가 바뀌었다"

        # 사용자 전역 파일은 그대로여야 한다
        assert open(user_settings).read() == before, "사용자 전역 설정을 건드렸다"

        # 커밋되는 파일이 아니라 개인 파일에 쓴다
        assert os.path.isfile(os.path.join(proj, ".claude", "settings.local.json")), "settings.local.json이 없다"
        assert not os.path.exists(os.path.join(proj, ".claude", "settings.json")), "공유 설정 파일을 만들었다"

        # 프로젝트 공유 설정보다 로컬이 이긴다
        json.dump({"enabledPlugins": {"a@m": True}}, open(os.path.join(proj, ".claude", "settings.json"), "w"))
        assert hud.plugin_state(proj)[0]["a@m"] is False, "로컬이 공유 설정을 못 이긴다"

        # 기존 내용을 지우지 않는다
        lp = os.path.join(proj, ".claude", "settings.local.json")
        d = json.load(open(lp)); d["permissions"] = {"deny": ["Skill(x:y)"]}; json.dump(d, open(lp, "w"))
        hud.set_plugins({"a@m": True}, proj)
        assert json.load(open(lp))["permissions"]["deny"] == ["Skill(x:y)"], "다른 설정을 날렸다"

        ok, err = hud.set_plugins({"nope@m": True}, proj)
        assert not ok, "모르는 플러그인을 그냥 적었다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
