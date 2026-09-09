"""apply_skill_group()이 링크만 만들고 링크만 지우는지 본다.
   진짜 폴더를 지우면 사용자 파일이 날아가므로 그게 이 테스트의 핵심이다.
   python3 test_skill_groups.py"""
import importlib.util, json, os, shutil, tempfile

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
        # 가짜 플러그인 둘 + 그룹 둘
        pa, pb = os.path.join(tmp, "pa", "skills"), os.path.join(tmp, "pb", "skills")
        make_skill(pa, "vid-one"); make_skill(pa, "vid-two")
        make_skill(pb, "dev-one")
        hud.MODES_FILE = os.path.join(tmp, "modes.json")
        json.dump({"video": ["A"], "dev": ["B"]}, open(hud.MODES_FILE, "w"))
        hud.plugin_skills = lambda: {
            "A": hud._walk_skills(pa),
            "B": hud._walk_skills(pb),
        }
        proj = os.path.join(tmp, "proj"); os.makedirs(proj)

        ok, msg = hud.apply_skill_group("video", proj)
        assert ok, msg
        # 링크 대상을 상수에서 읽지 말고 못박아 확인한다. 상수를 순회하면 폴더가
        # 하나 빠져도 테스트가 그대로 통과해 지원이 조용히 사라진다.
        for lit in (".claude/skills", ".agents/skills"):
            p_ = os.path.join(proj, lit, "vid-one")
            assert os.path.islink(p_), f"{lit}에 링크가 없다 -- 그 도구들이 스킬을 못 본다"
        for d in hud.GROUP_LINK_DIRS:
            for sk in ("vid-one", "vid-two"):
                p = hud._link_path(proj, d, sk)
                assert os.path.islink(p), f"링크가 안 생김: {p}"
                assert os.path.isfile(os.path.join(p, "SKILL.md")), "링크 너머가 안 읽힘"
            assert not os.path.exists(hud._link_path(proj, d, "dev-one")), "다른 그룹이 켜짐"

        # 그룹을 바꾸면 앞 그룹 링크는 사라져야 한다
        ok, msg = hud.apply_skill_group("dev", proj)
        assert ok, msg
        for d in hud.GROUP_LINK_DIRS:
            assert os.path.islink(hud._link_path(proj, d, "dev-one")), "새 그룹이 안 켜짐"
            assert not os.path.exists(hud._link_path(proj, d, "vid-one")), "옛 그룹 링크가 남음"

        # 사용자가 직접 둔 진짜 폴더는 절대 지우지 않는다
        real = make_skill(os.path.join(proj, hud.GROUP_LINK_DIRS[0]), "vid-one")
        ok, _ = hud.apply_skill_group("dev", proj)
        assert ok
        assert os.path.isdir(real) and not os.path.islink(real), "진짜 폴더를 지웠다"
        assert os.path.isfile(os.path.join(real, "SKILL.md")), "진짜 폴더 내용이 날아갔다"

        # 끄기: 그룹 없이 호출하면 관리 중인 링크가 전부 빠진다
        ok, _ = hud.apply_skill_group("", proj)
        assert ok
        for d in hud.GROUP_LINK_DIRS:
            assert not os.path.islink(hud._link_path(proj, d, "dev-one")), "끄기가 안 됨"
        assert os.path.isdir(real), "끄기가 진짜 폴더를 지웠다"

        # 원본 스킬은 언제나 그대로다
        assert os.path.isfile(os.path.join(pa, "vid-one", "SKILL.md")), "원본이 손상됨"
        assert os.path.isfile(os.path.join(pb, "dev-one", "SKILL.md")), "원본이 손상됨"
        print("PASS")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
