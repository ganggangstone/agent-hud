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


def test_codex_skips_empty_override():
    tmp = env()
    try:
        proj = os.path.join(tmp, "p"); real = w(os.path.join(proj, "AGENTS.md"))
        w(os.path.join(proj, "AGENTS.override.md"), "")
        assert hud.session_instructions(proj)["Codex"] == [real]
        over = w(os.path.join(proj, "AGENTS.override.md"))
        assert hud.session_instructions(proj)["Codex"] == [over]
        gl = w(os.path.join(hud.HOME, ".codex", "AGENTS.md")); go = w(os.path.join(hud.HOME, ".codex", "AGENTS.override.md"))
        assert hud.session_instructions(proj)["Codex"] == [go, over]
    finally:
        shutil.rmtree(tmp)


def test_codex_walks_from_git_root():
    tmp = env()
    try:
        repo = os.path.join(tmp, "r"); os.makedirs(os.path.join(repo, ".git"))
        w(os.path.join(tmp, "AGENTS.md"))                # 저장소 밖: 안 읽는다
        top = w(os.path.join(repo, "AGENTS.md")); leaf = w(os.path.join(repo, "pkg", "a", "AGENTS.md"))
        assert hud.session_instructions(os.path.join(repo, "pkg", "a"))["Codex"] == [top, leaf]
        os.rmdir(os.path.join(repo, ".git"))             # 루트가 없으면 현재 폴더만
        assert hud.session_instructions(os.path.join(repo, "pkg", "a"))["Codex"] == [leaf]
        os.environ["CODEX_HOME"] = os.path.join(tmp, "ch")
        ch = w(os.path.join(tmp, "ch", "AGENTS.md"))
        assert hud.session_instructions(os.path.join(repo, "pkg", "a"))["Codex"] == [ch, leaf]
    finally:
        os.environ.pop("CODEX_HOME", None)
        shutil.rmtree(tmp)


def test_agy_cli_skill_paths():
    tmp = env()
    try:
        base = os.path.join(hud.HOME, ".gemini", "antigravity-cli")
        w(os.path.join(base, "skills", "cli-skill", "SKILL.md"), "---\nname: cli-skill\ndescription: x\n---\n")
        w(os.path.join(base, "plugins", "pg", "skills", "pl-skill", "SKILL.md"), "---\nname: pl-skill\ndescription: x\n---\n")
        idx = hud._skill_root_index(tmp)
        assert idx["cli-skill"]["agents"] == ["Antigravity"], idx
        assert idx["pl-skill"]["agents"] == ["Antigravity"], idx
    finally:
        shutil.rmtree(tmp)


def test_claude_hierarchy_and_rules():
    tmp = env()
    try:
        a = os.path.join(tmp, "a"); p = os.path.join(a, "p"); os.makedirs(p)
        par = w(os.path.join(a, "CLAUDE.md")); pdot = w(os.path.join(a, ".claude", "CLAUDE.md"))
        prule = w(os.path.join(a, ".claude", "rules", "r.md")); ploc = w(os.path.join(a, "CLAUDE.local.md"))
        w(os.path.join(a, "AGENTS.md")); w(os.path.join(p, "AGENTS.md"))
        dot = w(os.path.join(p, ".claude", "CLAUDE.md")); deep = w(os.path.join(p, ".claude", "rules", "deep", "d.md"))
        top = w(os.path.join(p, ".claude", "rules", "top.md"))
        w(os.path.join(p, ".claude", "rules", "scoped.md"), "---\npaths:\n  - \"**/*.zzz\"\n---\nx\n")
        w(os.path.join(p, ".claude", "rules", "n.txt")); loc = w(os.path.join(p, "CLAUDE.local.md"))
        w(os.path.join(p, "sub", "CLAUDE.md"))
        ur = w(os.path.join(hud.CLAUDE_DIR, "rules", "u.md"))
        got = hud.session_instructions(p)["Claude Code"]
        assert got == [ur, par, pdot, prule, ploc, dot, top, deep, loc], got
        rows = {r["path"]: r for r in hud.collect_instructions({"project_dir": p})["files"]}
        for f in got:
            assert f in rows, f
        assert rows[dot]["scope"] == "project" and rows[par]["scope"] == "global"
    finally:
        shutil.rmtree(tmp)


def test_claude_reads_agents_only_without_claude_md():
    tmp = env()
    try:
        b = os.path.join(tmp, "b"); q = os.path.join(b, "q"); os.makedirs(q)
        pa = w(os.path.join(b, "AGENTS.md")); qa = w(os.path.join(q, "AGENTS.md")); qd = w(os.path.join(q, ".claude", "AGENTS.md"))
        gl = w(os.path.join(hud.CLAUDE_DIR, "CLAUDE.md"))   # 전역 CLAUDE.md는 대체 판정에 안 들어간다
        assert hud.session_instructions(q)["Claude Code"] == [gl, pa, qa, qd]
        c = w(os.path.join(b, "CLAUDE.md"))
        assert hud.session_instructions(q)["Claude Code"] == [gl, c]
    finally:
        shutil.rmtree(tmp)


def test_antigravity_instructions():
    tmp = env()
    try:
        c = os.path.join(tmp, "c"); r = os.path.join(c, "r"); os.makedirs(r)
        w(os.path.join(c, "AGENTS.md"))         # 상위 폴더는 안 읽는다(측정)
        g = w(os.path.join(hud.HOME, ".gemini", "GEMINI.md"))
        cfg = w(os.path.join(hud.HOME, ".gemini", "config", "rules", "g.md"), "---\ntrigger: always_on\n---\n")
        ag = w(os.path.join(r, "AGENTS.md")); ge = w(os.path.join(r, "GEMINI.md"))
        da = w(os.path.join(r, ".agents", "AGENTS.md")); dg = w(os.path.join(r, ".agents", "GEMINI.md"))
        on = w(os.path.join(r, ".agents", "rules", "on.md"), "---\ntrigger: always_on\n---\n@[l](inc2.md)\n@inc.md\n")
        inc2 = w(os.path.join(r, ".agents", "rules", "inc2.md")); w(os.path.join(r, ".agents", "rules", "inc.md"))
        w(os.path.join(r, ".agents", "rules", "plain.md")); w(os.path.join(r, ".agents", "rules", "man.md"), "---\ntrigger: manual\n---\n")
        got = hud.session_instructions(r)["Antigravity"]
        assert got == [g, cfg, ag, ge, da, dg, on, inc2], got
    finally:
        shutil.rmtree(tmp)


def test_same_name_merges_only_same_file():
    tmp = env()
    try:
        p = os.path.join(tmp, "p")
        cl = w(os.path.join(p, ".claude", "skills", "same", "SKILL.md"), "---\nname: same\ndescription: CLAUDE\n---\n")
        ag = w(os.path.join(p, ".agents", "skills", "same", "SKILL.md"), "---\nname: same\ndescription: AGENTS\n---\n")
        rows = [r for r in hud.collect_skills({"project_dir": p})["rows"] if not r["name"]][0]["skills"]
        by = {s["desc"]: s for s in rows if s["name"] == "same"}
        assert set(by) == {"CLAUDE", "AGENTS"}, rows
        assert "Claude Code" in by["CLAUDE"]["agents"] and "Codex" not in by["CLAUDE"]["agents"]
        assert "Codex" in by["AGENTS"]["agents"] and "Claude Code" not in by["AGENTS"]["agents"]
        # 링크로 공유한 같은 파일은 한 행이다
        shutil.rmtree(os.path.join(p, ".agents", "skills", "same"))
        os.symlink(os.path.dirname(cl), os.path.join(p, ".agents", "skills", "same"))
        rows = [r for r in hud.collect_skills({"project_dir": p})["rows"] if not r["name"]][0]["skills"]
        assert [s["name"] for s in rows].count("same") == 1, rows
        assert "Codex" in rows[0]["agents"] and "Claude Code" in rows[0]["agents"]
        # Claude Code는 같은 이름이면 전역이 프로젝트를 이긴다(공식 문서). 프로젝트 쪽은 Claude 뱃지를 잃는다.
        w(os.path.join(hud.CLAUDE_DIR, "skills", "same", "SKILL.md"), "---\nname: same\ndescription: GLOBAL\n---\n")
        rows = [r for r in hud.collect_skills({"project_dir": p})["rows"] if not r["name"]][0]["skills"]
        by = {s["desc"]: s for s in rows if s["name"] == "same"}
        assert "Claude Code" in by["GLOBAL"]["agents"] and "Claude Code" not in by["CLAUDE"]["agents"], by
    finally:
        shutil.rmtree(tmp)


def test_unassign_restores_switches():
    tmp = env()
    try:
        p = os.path.join(tmp, "p"); os.makedirs(p)
        hud.SETS_FILE = os.path.join(tmp, "sets.json"); hud.MODES_FILE = os.path.join(tmp, "modes.json")
        for n in ("in-g", "out-g", "was-off", "user-set"):
            w(os.path.join(hud.CLAUDE_DIR, "skills", n, "SKILL.md"), f"---\nname: {n}\ndescription: x\n---\n")
        d = os.path.join(hud.CLAUDE_DIR, "plugins"); ip = os.path.join(tmp, "pl"); os.makedirs(os.path.join(ip, "skills"))
        w(os.path.join(d, "installed_plugins.json"), json.dumps({"plugins": {"a@m": [{"installPath": ip}], "b@m": [{"installPath": ip}]}}))
        json.dump({"g": {"plugins": ["a@m"], "skills": ["in-g"]}, "h": {"plugins": [], "skills": []}}, open(hud.MODES_FILE, "w"))
        local = os.path.join(p, ".claude", "settings.local.json")
        before = {"keep": 1, "enabledPlugins": {"b@m": True}, "skillOverrides": {"was-off": "off"}}
        w(local, json.dumps(before))
        ok, err = hud.assign_set("g", p); assert ok, err
        cur = json.load(open(local))
        assert cur["enabledPlugins"] == {"a@m": True, "b@m": False} and cur["skillOverrides"]["out-g"] == "off", cur
        ok, err = hud.assign_set("h", p); assert ok, err     # 그룹을 바꿔도 처음 값을 기억한다
        ok, err = hud.assign_set("", p); assert ok, err
        assert json.load(open(local)) == before, json.load(open(local))
        # 적용 뒤 사용자가 직접 바꾼 값은 남긴다
        ok, err = hud.assign_set("g", p); assert ok, err
        cur = json.load(open(local)); cur["skillOverrides"]["user-set"] = "user-invocable-only"; cur["enabledPlugins"]["b@m"] = True
        cur["skillOverrides"]["out-g"] = "user-invocable-only"
        json.dump(cur, open(local, "w"))
        ok, err = hud.assign_set("", p); assert ok, err
        got = json.load(open(local))
        assert got["skillOverrides"]["out-g"] == "user-invocable-only" and got["skillOverrides"]["was-off"] == "off", got
    finally:
        shutil.rmtree(tmp)


def test_other_agents_disabled_skills():
    tmp = env()
    try:
        p = os.path.join(tmp, "p")
        for n in ("cx", "gm", "gu", "cp", "cr", "ok"):
            w(os.path.join(p, ".agents", "skills", n, "SKILL.md"), f"---\nname: {n}\ndescription: x\n---\n")
        cx = os.path.join(p, ".agents", "skills", "cx", "SKILL.md")
        w(os.path.join(hud.HOME, ".codex", "config.toml"), f"[[skills.config]]\npath = {json.dumps(cx)}\nenabled = false\n")
        w(os.path.join(p, ".gemini", "settings.json"), json.dumps({"skills": {"disabled": ["gm"]}}))
        w(os.path.join(hud.HOME, ".gemini", "settings.json"), json.dumps({"skills": {"disabled": ["gu"]}}))
        w(os.path.join(hud.HOME, ".copilot", "settings.json"), json.dumps({"disabledSkills": ["cp"]}))
        w(os.path.join(p, ".github", "copilot", "settings.json"), json.dumps({"disabledSkills": ["cr"]}))
        rows = [r for r in hud.collect_skills({"project_dir": p})["rows"] if not r["name"]][0]["skills"]
        by = {s["name"]: s["agents"] for s in rows}
        assert "Codex" not in by["cx"] and "Codex" in by["ok"], by
        assert "Gemini CLI" not in by["gm"] and "Gemini CLI" not in by["gu"] and "Gemini CLI" in by["ok"], by
        assert "Copilot" not in by["cp"] and "Copilot" not in by["cr"] and "Copilot" in by["ok"], by
        for bad in ("[[skills.config", "\xff"):
            open(os.path.join(hud.HOME, ".codex", "config.toml"), "w", errors="replace").write(bad)
            hud.collect_skills({"project_dir": p})              # 깨진 설정 파일로 죽지 않는다
    finally:
        shutil.rmtree(tmp)


def test_robust_against_bad_files():
    tmp = env()
    try:
        p = os.path.join(tmp, "p")
        # 읽을 수 없는 스킬 파일과 규칙 폴더로 수집이 죽지 않는다
        locked = w(os.path.join(p, ".claude", "skills", "locked", "SKILL.md"), "---\nname: locked\ndescription: x\n---\n")
        w(os.path.join(p, ".agents", "skills", "locked", "SKILL.md"), "---\nname: locked\ndescription: y\n---\n")
        os.chmod(locked, 0)
        rules = os.path.join(p, ".agents", "rules"); os.makedirs(rules); os.chmod(rules, 0)
        try:
            hud._skill_root_index(p)
            hud.session_instructions(p)
        finally:
            os.chmod(locked, 0o644); os.chmod(rules, 0o755)
        # 규칙 폴더의 순환 링크에서 멈춘다
        r = os.path.join(p, ".claude", "rules"); w(os.path.join(r, "a.md"))
        os.symlink(r, os.path.join(r, "loop"))
        assert [f for f in hud._claude_rules(r)] == [os.path.join(r, "a.md")], hud._claude_rules(r)
        # @[..](..) 사슬이 아주 길어도 죽지 않는다
        d = os.path.join(p, "c")
        for i in range(3000):
            w(os.path.join(d, f"{i}.md"), f"@[n]({i + 1}.md)\n")
        assert len(hud._agy_expand(os.path.join(d, "0.md"), set())) < 100
    finally:
        shutil.rmtree(tmp)


def test_reapply_keeps_user_change_and_failed_restore_keeps_record():
    tmp = env()
    try:
        p = os.path.join(tmp, "p"); os.makedirs(p)
        hud.SETS_FILE = os.path.join(tmp, "sets.json"); hud.MODES_FILE = os.path.join(tmp, "modes.json")
        for n in ("a", "b", "c", "z"):
            w(os.path.join(hud.CLAUDE_DIR, "skills", n, "SKILL.md"), f"---\nname: {n}\ndescription: x\n---\n")
        json.dump({"noa": {"plugins": [], "skills": ["b", "c", "z"]}}, open(hud.MODES_FILE, "w"))
        local = os.path.join(p, ".claude", "settings.local.json")
        w(local, json.dumps({"skillOverrides": {"c": "user-invocable-only"}}))
        ok, err = hud.assign_set("noa", p); assert ok, err
        cur = json.load(open(local)); assert cur["skillOverrides"]["a"] == "off", cur
        # 적용 뒤 사용자가 값을 바꾸고 재적용해도, 해제가 그 값을 지우지 않는다
        cur["skillOverrides"]["a"] = "user-invocable-only"; json.dump(cur, open(local, "w"))
        ok, err = hud.assign_set("noa", p); assert ok, err
        assert json.load(open(local))["skillOverrides"]["a"] == "off"      # 재적용은 그룹 값을 다시 쓴다
        cur = json.load(open(local)); cur["skillOverrides"]["q"] = "off"; json.dump(cur, open(local, "w"))
        ok, err = hud.assign_set("", p); assert ok, err
        got = json.load(open(local))["skillOverrides"]
        assert got.get("q") == "off", "그룹과 무관한 사용자 값이 지워졌다"
        assert "a" not in got or got["a"] == "user-invocable-only", got
        # 복원 쓰기가 실패하면 기록을 남겨 다시 시도할 수 있다
        ok, err = hud.assign_set("noa", p); assert ok, err
        real = hud._write_local
        hud._write_local = lambda *a: (False, "disk")
        try:
            ok, err = hud.assign_set("", p); assert not ok
        finally:
            hud._write_local = real
        assert p in json.load(open(hud.SETS_FILE + ".restore")), "복원 기록이 사라졌다"
        ok, err = hud.assign_set("", p); assert ok, err
        assert p not in json.load(open(hud.SETS_FILE + ".restore"))
    finally:
        shutil.rmtree(tmp)


#TESTS

if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
    print("PASS")
