"""link_skill()이 원본 위치와 무관하게 빈 폴더만 채우는지, 그리고 링크만 지우는지 본다.
   방향(claude->agents, agents->claude)을 따지지 않는 것이 이 함수의 요점이다.
   python3 test_link_skill.py"""
import importlib.util, os, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("hud", os.path.join(HERE, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def make_skill(root, name):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: x\n---\n")
    return d


def main():
    tmp = tempfile.mkdtemp()
    try:
        # 원본이 서로 다른 곳에 있는 스킬 셋
        from_plugin = make_skill(os.path.join(tmp, "plug", "skills"), "from-plugin")
        from_agents = make_skill(os.path.join(tmp, "home", ".agents", "skills"), "from-agents")
        from_claude = make_skill(os.path.join(tmp, "home", ".claude", "skills"), "from-claude")
        hud.HOME = os.path.join(tmp, "home")
        hud.plugin_skills = lambda: {"P": {"from-plugin": from_plugin}}

        proj = os.path.join(tmp, "proj"); os.makedirs(proj)
        src = hud.skill_sources(proj)
        for n in ("from-plugin", "from-agents", "from-claude"):
            assert n in src, f"원본을 못 찾음: {n}"

        for name, origin in (("from-plugin", from_plugin), ("from-agents", from_agents),
                             ("from-claude", from_claude)):
            ok, err = hud.link_skill(name, True, proj)
            assert ok, err
            assert hud.skill_is_shared(proj, name), f"{name}: 모든 폴더에 안 걸렸다"
            for d in hud.GROUP_LINK_DIRS:
                p = hud._link_path(proj, d, name)
                assert os.path.islink(p), f"{name}: {d}에 링크가 없다"
                assert os.path.isfile(os.path.join(p, "SKILL.md")), "링크 너머가 안 읽힌다"
            assert os.path.isfile(os.path.join(origin, "SKILL.md")), "원본이 손상됐다"

        # 끄면 링크만 사라지고 원본은 남는다
        ok, err = hud.link_skill("from-agents", False, proj)
        assert ok, err
        assert not hud.skill_is_shared(proj, "from-agents"), "안 꺼졌다"
        for d in hud.GROUP_LINK_DIRS:
            assert not os.path.exists(hud._link_path(proj, d, "from-agents")), "링크가 남았다"
        assert os.path.isfile(os.path.join(from_agents, "SKILL.md")), "원본을 지웠다"

        # 사용자가 직접 둔 진짜 폴더는 절대 건드리지 않는다
        real = make_skill(os.path.join(proj, hud.GROUP_LINK_DIRS[0]), "handmade")
        hud.plugin_skills = lambda: {"P": {"handmade": from_plugin}}
        hud.link_skill("handmade", True, proj)
        assert not os.path.islink(real), "진짜 폴더를 링크로 덮었다"
        hud.link_skill("handmade", False, proj)
        assert os.path.isdir(real) and os.path.isfile(os.path.join(real, "SKILL.md")), "진짜 폴더를 지웠다"

        ok, err = hud.link_skill("nope", True, proj)
        assert not ok and err == "unknown skill", "모르는 스킬을 그냥 처리했다"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
