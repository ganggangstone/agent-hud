"""스킬 차단은 커밋되지 않는 settings.local.json에 써야 한다(ADR 3). 공유 settings.json은 만들지 않는다.
   python3 tests/test_skill_deny_scope.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def main():
    tmp = tempfile.mkdtemp()
    try:
        hud.known_plugin_names = lambda: {"p@m"}
        proj = os.path.join(tmp, "proj"); os.makedirs(proj)
        shared = os.path.join(proj, ".claude", "settings.json")
        local = os.path.join(proj, ".claude", "settings.local.json")

        ok, err = hud.modify_skill_permission("block", "p@m", "s1", proj)
        assert ok, err
        assert not os.path.exists(shared), "공유 settings.json에 차단을 썼다"
        assert "Skill(p@m:s1)" in json.load(open(local))["permissions"]["deny"], "settings.local.json에 차단이 없다"
        assert hud.skill_denies(proj) == {"Skill(p@m:s1)"}, hud.skill_denies(proj)

        # 예전 버전이 공유 파일에 남긴 차단도 차단으로 보이고, 허용하면 거기서도 지워진다
        os.makedirs(os.path.dirname(shared), exist_ok=True)
        json.dump({"permissions": {"deny": ["Skill(p@m:old)", "Bash(rm:*)"]}}, open(shared, "w"))
        assert "Skill(p@m:old)" in hud.skill_denies(proj), "공유 파일의 기존 차단을 못 읽는다"
        ok, err = hud.modify_skill_permission("unblock", "p@m", "old", proj)
        assert ok, err
        assert "Skill(p@m:old)" not in hud.skill_denies(proj), "허용했는데 여전히 차단"
        assert json.load(open(shared))["permissions"]["deny"] == ["Bash(rm:*)"], "공유 파일의 다른 규칙을 날렸다"

        # 로컬 파일의 다른 설정은 보존한다
        d = json.load(open(local)); d["enabledPlugins"] = {"p@m": True}; json.dump(d, open(local, "w"))
        hud.modify_skill_permission("unblock", "p@m", "s1", proj)
        assert json.load(open(local))["enabledPlugins"] == {"p@m": True}, "로컬의 다른 설정을 날렸다"
        assert hud.skill_denies(proj) == {"Bash(rm:*)"}, hud.skill_denies(proj)
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
