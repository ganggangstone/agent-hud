"""_loaded_count()가 실제로 로드되는 스킬만 세는지 본다.
   꺼진 플러그인과 차단한 스킬은 컨텍스트에 안 올라가므로 세면 안 된다.
   python3 test_loaded.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("hud", os.path.join(HERE, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)

C = ["Claude Code"]
OTHERS = ["Codex", "Cursor"]


def sk(name, agents=C, blocked=False):
    return {"id": name, "agents": agents, "blocked": blocked}


def main():
    rows = [
        {"name": "on@m", "enabled": True, "skills": [sk("a"), sk("b"), sk("c", blocked=True)]},
        {"name": "off@m", "enabled": False, "skills": [sk("d"), sk("e")]},
        # 플러그인 밖의 스킬: Claude Code가 보는 것만 센다
        {"name": "", "enabled": None, "skills": [sk("f"), sk("g", agents=OTHERS)]},
    ]
    got = hud._loaded_count(rows)
    assert got == 3, f"켜진 플러그인 2 + 단독 1 = 3이어야 하는데 {got}"

    # 플러그인을 끄면 그만큼 준다
    rows[0]["enabled"] = False
    assert hud._loaded_count(rows) == 1, "꺼진 플러그인의 스킬을 세고 있다"

    # 차단을 풀면 하나 는다
    rows[0]["enabled"] = True
    rows[0]["skills"][2]["blocked"] = False
    assert hud._loaded_count(rows) == 4, "차단 해제를 반영하지 않는다"

    # 다른 에이전트만 보는 스킬은 Claude Code 컨텍스트에 안 올라간다
    rows[2]["skills"][0]["agents"] = OTHERS
    assert hud._loaded_count(rows) == 3, "Claude Code가 못 보는 스킬을 세고 있다"

    assert hud._loaded_count([]) == 0
    print("PASS")


if __name__ == "__main__":
    main()
