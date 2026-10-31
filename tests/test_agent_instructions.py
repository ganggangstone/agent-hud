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


def test_codex_empty_files_measured():
    """Codex 0.166 측정: 프로젝트 폴더는 처음 발견한 파일 하나만 쓰고, 비어 있으면 그 폴더 지침은 없다.
    전역 폴더는 비어 있지 않은 첫 파일을 쓴다."""
    tmp = env()
    try:
        proj = os.path.join(tmp, "p"); real = w(os.path.join(proj, "AGENTS.md"))
        assert hud.session_instructions(proj)["Codex"] == [real]
        w(os.path.join(proj, "AGENTS.override.md"), "")
        assert hud.session_instructions(proj)["Codex"] == [], "빈 override가 AGENTS.md를 막는다"
        over = w(os.path.join(proj, "AGENTS.override.md"))
        assert hud.session_instructions(proj)["Codex"] == [over]
        gl = w(os.path.join(hud.HOME, ".codex", "AGENTS.md")); w(os.path.join(hud.HOME, ".codex", "AGENTS.override.md"), "")
        assert hud.session_instructions(proj)["Codex"] == [gl, over], "전역은 빈 파일을 건너뛴다"
    finally:
        shutil.rmtree(tmp)


def test_codex_fallback_and_byte_limit_measured():
    tmp = env()
    try:
        cfg = w(os.path.join(hud.HOME, ".codex", "config.toml"), 'project_doc_fallback_filenames = ["TEAM.md"]\nproject_doc_max_bytes = 10\n')
        g = w(os.path.join(hud.HOME, ".codex", "AGENTS.md"), "g" * 50)      # 전역은 한도에 안 들어간다
        r = os.path.join(tmp, "r"); os.makedirs(os.path.join(r, ".git"))
        top = w(os.path.join(r, "AGENTS.md"), "a" * 8)
        team = w(os.path.join(r, "x", "TEAM.md"), "b" * 8)
        w(os.path.join(r, "x", "y", "AGENTS.md"), "c" * 8)                   # 한도를 넘어 안 읽힌다
        got = hud.session_instructions(os.path.join(r, "x", "y"))["Codex"]
        assert got == [g, top, team], got
        real = hud.count_tokens
        hud.count_tokens = lambda texts: ("ok", {t: len(t) for t in texts})
        try:
            tk = {"state": "ok", "agents": {"Codex": {"skills": 0, "measured": 0, "tokens": 0}}}
            load = hud.session_load(os.path.join(r, "x", "y"), tk)["Codex"]
        finally:
            hud.count_tokens = real
        assert load["tokens"] == 50 + 8 + 2 and load["truncated"] is True, load
        w(cfg, 'project_doc_fallback_filenames = ["TEAM.md"]\nproject_doc_max_bytes = 0\n')
        assert hud.session_instructions(os.path.join(r, "x"))["Codex"] == [g], "0이면 프로젝트 지침을 읽지 않는다"
        w(cfg, "[[broken")
        assert top in hud.session_instructions(os.path.join(r, "x"))["Codex"], "깨진 설정이면 기본값으로 본다"
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
        for n in ("cx", "cp", "cr", "ok"):
            w(os.path.join(p, ".agents", "skills", n, "SKILL.md"), f"---\nname: {n}\ndescription: x\n---\n")
        cx = os.path.join(p, ".agents", "skills", "cx", "SKILL.md")
        w(os.path.join(hud.HOME, ".codex", "config.toml"), f"[[skills.config]]\npath = {json.dumps(cx)}\nenabled = false\n")
        w(os.path.join(hud.HOME, ".copilot", "settings.json"), json.dumps({"disabledSkills": ["cp"]}))
        w(os.path.join(p, ".github", "copilot", "settings.json"), json.dumps({"disabledSkills": ["cr"]}))
        rows = [r for r in hud.collect_skills({"project_dir": p})["rows"] if not r["name"]][0]["skills"]
        by = {s["name"]: s["agents"] for s in rows}
        assert "Codex" not in by["cx"] and "Codex" in by["ok"], by
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


def test_install_does_not_copy_example_groups():
    text = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read()
    assert "modes.json" not in text, "첫 설치에 자리표시자 그룹을 만들면 안 된다"
    assert not os.path.exists(os.path.join(ROOT, "modes.json.example"))
    tmp = env()
    try:
        hud.MODES_FILE = os.path.join(tmp, "none.json")
        assert hud.collect_groups({"project_dir": tmp})["groups"] == []     # 그룹 없이 시작해도 화면이 뜬다
    finally:
        shutil.rmtree(tmp)


def test_old_service_warning_only_on_brew_with_old_plist():
    tmp = env()
    real = hud.brew_prefix
    try:
        hud.brew_prefix = lambda *a: "/opt/homebrew"
        assert hud.collect_update({})["old_service"] is False
        w(os.path.join(hud.HOME, "Library", "LaunchAgents", "com.agent-hud.plist"))
        assert hud.collect_update({})["old_service"] is True
        hud.brew_prefix = lambda *a: None       # 클론 설치본에게 이 서비스는 자기 자신이다
        assert hud.collect_update({})["old_service"] is False
        assert "com.agent-hud" in hud.PAGE and "oldServiceBanner" in hud.PAGE
    finally:
        hud.brew_prefix = real
        shutil.rmtree(tmp)


def test_related_documents():
    tmp = env()
    try:
        p = os.path.join(tmp, "p")
        g1 = w(os.path.join(p, "guides", "git.md")); g2 = w(os.path.join(p, "docs", "rel.md"))
        imp = w(os.path.join(p, "imp.md")); w(os.path.join(p, "code.md")); w(os.path.join(p, "secret.key"))
        body = ("| 언제 | 파일 |\n|---|---|\n| 커밋 | `guides/git.md` |\n"
                "[관련](docs/rel.md#절)\n[웹](https://example.com/a.md)\n`없는파일.md`\n`secret.key`\n"
                "@imp.md\n[자기](CLAUDE.md)\n```\n`code.md`\n```\n`docs/rel.md`\n")
        claude = w(os.path.join(p, "CLAUDE.md"), body)
        real = os.path.expanduser
        os.path.expanduser = lambda q: q.replace("~", hud.HOME, 1) if q.startswith("~") else real(q)
        try:
            rows = {r["path"]: r for r in hud.collect_instructions({"project_dir": p})["files"]}
        finally:
            os.path.expanduser = real
        assert rows[claude]["related"] == [g1, g2], rows[claude]["related"]     # 있는 문서만, 중복 없이
        assert g1 in hud.READABLE_PATHS, "화면에서 열 수 있어야 한다"
        reads = hud.session_instructions(p)["Claude Code"]
        assert g1 not in reads and g2 not in reads, "시작 합계에 들어가면 안 된다"
        assert g1 not in rows and g2 not in rows, "지침 행으로 만들지 않는다"
        assert all("related" in r for r in rows.values())
    finally:
        shutil.rmtree(tmp)


def test_related_documents_stay_in_scope():
    """다른 사람의 저장소가 적은 경로로 이 컴퓨터의 파일을 열 수 있으면 안 된다."""
    tmp = env()
    try:
        p = os.path.join(tmp, "p")
        secret = w(os.path.join(hud.HOME, ".aws", "credentials.txt"))
        ok = w(os.path.join(p, "ok.md")); os.symlink(secret, os.path.join(p, "leak.txt"))
        outside = w(os.path.join(tmp, "outside.md"))
        claude = w(os.path.join(p, "CLAUDE.md"), f"[a]({secret})\n`leak.txt`\n`../outside.md`\n`ok.md`\n")
        row = hud._file_row("CLAUDE.md", claude)
        got = hud._related_docs(claude, p)
        assert got == [ok], got
        # 전역 지침은 자기 폴더의 문서를 가리킬 수 있다
        guide = w(os.path.join(hud.HOME, ".codex", "guides", "git.md"))
        g = w(os.path.join(hud.HOME, ".codex", "AGENTS.md"), f"`{guide}`\n`guides/git.md`\n")
        assert hud._related_docs(g, p) == [guide]
        # 링크가 많아도 상한에서 멈춘다
        many = w(os.path.join(p, "many.md"), "`ok.md`\n" + "".join(f"`d{i}.md`\n" for i in range(hud.RELATED_MAX + 20)))
        for i in range(hud.RELATED_MAX + 20):
            w(os.path.join(p, f"d{i}.md"))
        assert len(hud._related_docs(many, p)) == hud.RELATED_MAX
    finally:
        shutil.rmtree(tmp)


def test_old_service_command_survives_unloaded_service():
    assert "com.agent-hud && rm" not in hud.PAGE, "등록이 없으면 bootout이 실패해 rm까지 못 간다"
    assert "돌며" not in hud.PAGE, "plist만 보고 돌고 있다고 단정하지 않는다"


def test_codex_limit_applies_to_project_under_codex_home():
    tmp = env()
    try:
        home = os.path.join(hud.HOME, ".codex")
        w(os.path.join(home, "config.toml"), "project_doc_max_bytes = 10\n")
        g = w(os.path.join(home, "AGENTS.md"), "g" * 50)
        repo = os.path.join(home, "repo"); pf = w(os.path.join(repo, "AGENTS.md"), "p" * 100)
        assert hud.session_instructions(repo)["Codex"] == [g, pf]
        real = hud.count_tokens
        hud.count_tokens = lambda texts: ("ok", {t: len(t) for t in texts})
        try:
            load = hud.session_load(repo, {"state": "ok", "agents": {"Codex": {"skills": 0, "measured": 0, "tokens": 0}}})["Codex"]
        finally:
            hud.count_tokens = real
        assert load["tokens"] == 50 + 10 and load["truncated"] is True, load
        # 링크된 CODEX_HOME의 전역 파일은 한도가 0이어도 잘리지 않는다
        w(os.path.join(home, "config.toml"), "project_doc_max_bytes = 0\n")
        link = os.path.join(tmp, "linked"); os.symlink(home, link); os.environ["CODEX_HOME"] = link
        hud.count_tokens = lambda texts: ("ok", {t: len(t) for t in texts})
        try:
            load = hud.session_load(os.path.join(tmp, "elsewhere"), {"state": "ok", "agents": {"Codex": {"skills": 0, "measured": 0, "tokens": 0}}})["Codex"]
        finally:
            hud.count_tokens = real
        assert load["tokens"] == 50, load
    finally:
        os.environ.pop("CODEX_HOME", None)
        shutil.rmtree(tmp)


def test_codex_skill_paths_measured():
    """Codex 0.166 측정: 프로젝트 .agents, .codex와 $CODEX_HOME/skills를 읽고 .claude는 안 읽는다."""
    tmp = env()
    try:
        p = os.path.join(tmp, "p"); sk = "---\nname: {0}\ndescription: x\n---\n"
        for root, n in ((".agents", "a"), (".codex", "c"), (".claude", "l")):
            w(os.path.join(p, root, "skills", n, "SKILL.md"), sk.format(n))
        w(os.path.join(hud.HOME, ".codex", "skills", "h", "SKILL.md"), sk.format("h"))
        idx = hud._skill_root_index(p)
        assert "Codex" in idx["a"]["agents"] and "Codex" in idx["c"]["agents"] and "Codex" in idx["h"]["agents"], idx
        assert "Codex" not in idx["l"]["agents"], idx
        os.environ["CODEX_HOME"] = os.path.join(tmp, "ch")
        w(os.path.join(tmp, "ch", "skills", "e", "SKILL.md"), sk.format("e"))
        idx = hud._skill_root_index(p)
        assert "Codex" in idx["e"]["agents"], idx
        assert "Codex" not in idx["h"]["agents"], "CODEX_HOME을 옮기면 ~/.codex/skills는 Codex가 안 읽는다"
    finally:
        os.environ.pop("CODEX_HOME", None)
        shutil.rmtree(tmp)


def test_name_only_skill():
    tmp = env()
    try:
        p = os.path.join(tmp, "p")
        w(os.path.join(p, ".claude", "skills", "n", "SKILL.md"), "---\nname: n\ndescription: LONG DESCRIPTION\n---\n")
        w(os.path.join(p, ".claude", "settings.local.json"), json.dumps({"skillOverrides": {"n": "name-only"}}))
        seen = []
        real = hud.count_tokens
        hud.count_tokens = lambda texts: (seen.extend(texts), ("ok", {t: len(t) for t in texts}))[1]
        try:
            hud.collect_skills({"project_dir": p})
        finally:
            hud.count_tokens = real
        assert "n" in seen and not any("LONG DESCRIPTION" in t for t in seen), seen
    finally:
        shutil.rmtree(tmp)


def test_claude_strips_block_html_comments():
    tmp = env()
    try:
        p = os.path.join(tmp, "p")
        hidden = w(os.path.join(p, "hidden.md")); shown = w(os.path.join(p, "shown.md"))
        claude = w(os.path.join(p, "CLAUDE.md"), "<!-- note\n@hidden.md\n-->\nBODY\n@shown.md\n```\n<!-- KEEP -->\n```\n")
        assert hud.session_instructions(p)["Claude Code"] == [claude, shown]
        real = hud.count_tokens; seen = []
        hud.count_tokens = lambda texts: (seen.extend(texts), ("ok", {t: len(t) for t in texts}))[1]
        try:
            load = hud.session_load(p, {"state": "ok", "agents": {"Claude Code": {"skills": 0, "measured": 0, "tokens": 0}}})["Claude Code"]
        finally:
            hud.count_tokens = real
        stripped = "BODY\n@shown.md\n```\n<!-- KEEP -->\n```\n"
        assert stripped in seen and load["tokens"] == len(stripped) + len("x\n"), (seen, load)
    finally:
        shutil.rmtree(tmp)


def test_external_imports_need_approval():
    tmp = env()
    try:
        p = os.path.join(tmp, "p"); out = w(os.path.join(tmp, "out.md"))
        inside = w(os.path.join(p, "in.md"))
        claude = w(os.path.join(p, "CLAUDE.md"), "@../out.md\n@in.md\n")
        g = w(os.path.join(hud.CLAUDE_DIR, "CLAUDE.md"), "@../gout.md\n")          # 사용자 지침은 승인과 무관하다
        gout = w(os.path.join(hud.HOME, "gout.md"))
        state = os.path.join(hud.HOME, ".claude.json")
        assert hud.session_instructions(p)["Claude Code"] == [g, gout, claude, inside]
        rows = {r["path"]: r for r in hud.collect_instructions({"project_dir": p})["files"]}
        assert rows[out]["import_unconfirmed"] is True and rows[out]["claude_excluded"] is False, rows[out]
        assert rows[inside]["import_unconfirmed"] is False
        w(state, json.dumps({"projects": {p: {"hasClaudeMdExternalIncludesApproved": True}}}))
        assert out in hud.session_instructions(p)["Claude Code"], "승인했으면 읽힌다"
        rows = {r["path"]: r for r in hud.collect_instructions({"project_dir": p})["files"]}
        assert rows[out]["import_unconfirmed"] is False
        # 프로젝트 밖을 가리키는 규칙 링크도 승인이 필요하다
        w(state, "{}")
        rule_dir = os.path.join(p, ".claude", "rules"); os.makedirs(rule_dir)
        os.symlink(out, os.path.join(rule_dir, "linked.md"))
        assert out not in hud.session_instructions(p)["Claude Code"]
    finally:
        shutil.rmtree(tmp)


def test_review_findings_on_imports_and_rules():
    tmp = env()
    try:
        p = os.path.join(tmp, "p"); a = w(os.path.join(p, "a.md"))
        # 주석 뒤 같은 줄의 본문은 남는다
        assert hud._strip_block_html_comments("<!-- m --> body\nnext\n") == " body\nnext\n"
        # 프로젝트 안 파일이 깊이 제한으로 빠진 것은 승인 문제가 아니다
        for i in range(1, 7):
            w(os.path.join(p, f"h{i}.md"), f"@h{i + 1}.md\n")
        w(os.path.join(p, "h7.md"))
        w(os.path.join(p, "CLAUDE.md"), "@h1.md\n@a.md\n")
        rows = {os.path.basename(r["path"]): r for r in hud.collect_instructions({"project_dir": p})["files"] if r["exists"]}
        assert not any(r["import_unconfirmed"] for r in rows.values()), [(k, r["import_unconfirmed"]) for k, r in rows.items()]
        # 폴더째 프로젝트 밖으로 링크한 규칙도 승인이 필요하다. 상위 폴더의 규칙은 링크가 아니라 그대로 읽힌다.
        shared = os.path.join(tmp, "shared"); out = w(os.path.join(shared, "r.md"))
        rules = os.path.join(p, ".claude", "rules"); os.makedirs(rules); os.symlink(shared, os.path.join(rules, "shared"))
        parent = w(os.path.join(tmp, ".claude", "rules", "parent.md"))
        got = hud.session_instructions(p)["Claude Code"]
        assert parent in got, got
        assert not any(os.path.realpath(f) == out for f in got), got
    finally:
        shutil.rmtree(tmp)


def test_gemini_row_removed():
    tmp = env()
    try:
        p = os.path.join(tmp, "p")
        assert "Gemini CLI" not in hud.SKILL_AGENTS
        got = hud.session_instructions(p)
        assert "Gemini CLI" not in got
        g = w(os.path.join(hud.HOME, ".gemini", "GEMINI.md")); pg = w(os.path.join(p, "GEMINI.md"))
        assert hud.session_instructions(p)["Antigravity"] == [g, pg]
        rows = {r["path"]: r for r in hud.collect_instructions({"project_dir": p})["files"]}
        assert rows[g]["tool"] == "Antigravity" and rows[pg]["tool"] == "Antigravity", rows
        w(os.path.join(p, ".gemini", "skills", "only-gem", "SKILL.md"), "---\nname: only-gem\ndescription: x\n---\n")
        assert "only-gem" not in hud._skill_root_index(p)
        assert "Gemini CLI" not in hud.PAGE
    finally:
        shutil.rmtree(tmp)


#TESTS

if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
    print("PASS")
