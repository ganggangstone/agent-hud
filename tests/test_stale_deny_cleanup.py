"""예전 버전이 쓴 효과 없는 스킬 차단 항목을 지우는지 본다.
   Agent HUD는 Skill(플러그인@마켓플레이스:스킬) 형식으로 썼는데, Claude Code는 스킬 이름에 @를 쓰지 않아
   이 항목은 목록에서도 빠지지 않고 호출도 막지 못했다(센티널 실측, ADR 10).
   @가 든 Skill(...) 항목만 지우고, 사용자가 넣은 다른 규칙과 설정은 그대로 둔다.
   python3 tests/test_stale_deny_cleanup.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def main():
    tmp = tempfile.mkdtemp()
    try:
        proj = os.path.join(tmp, "proj")
        local = os.path.join(proj, ".claude", "settings.local.json")
        shared = os.path.join(proj, ".claude", "settings.json")
        write(local, {"enabledPlugins": {"p@m": True},
                      "permissions": {"deny": ["Skill(p@m:s1)", "Skill(sns-writing)", "Bash(rm:*)"]}})
        write(shared, {"model": "x", "permissions": {"deny": ["Skill(p@m:s2)"]}})

        removed = hud.remove_stale_skill_denies(proj)
        assert sorted(removed) == ["Skill(p@m:s1)", "Skill(p@m:s2)"], removed

        lo = json.load(open(local))
        assert lo["permissions"]["deny"] == ["Skill(sns-writing)", "Bash(rm:*)"], lo
        assert lo["enabledPlugins"] == {"p@m": True}, "다른 설정을 날렸다"

        sh = json.load(open(shared))
        assert "permissions" not in sh, "빈 permissions를 남겼다"
        assert sh["model"] == "x", "공유 설정의 다른 키를 날렸다"

        # 지울 게 없으면 파일을 다시 쓰지 않는다
        before = open(local, "rb").read()
        os.utime(local, (1, 1))
        assert hud.remove_stale_skill_denies(proj) == []
        assert open(local, "rb").read() == before and os.stat(local).st_mtime == 1, "지울 게 없는데 다시 썼다"

        # 설정 파일이 없어도 괜찮다
        empty = os.path.join(tmp, "empty"); os.makedirs(empty)
        assert hud.remove_stale_skill_denies(empty) == []
        assert not os.path.exists(os.path.join(empty, ".claude")), "없는 설정 파일을 만들었다"

        # 설정 파일이 JSON 객체가 아니어도 죽지 않는다
        weird = os.path.join(tmp, "weird")
        write(os.path.join(weird, ".claude", "settings.local.json"), ["not", "a", "dict"])
        assert hud.remove_stale_skill_denies(weird) == []

        # 서버 시작 시 등록된 프로젝트 전부를 정리한다
        other = os.path.join(tmp, "other")
        write(os.path.join(other, ".claude", "settings.local.json"),
              {"permissions": {"deny": ["Skill(q@n:t1)"]}})
        hud.known_projects = lambda: [proj, other]
        hud.cleanup_known_projects()
        assert "permissions" not in json.load(open(os.path.join(other, ".claude", "settings.local.json")))
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
