"""실제 임시 Git 저장소와 worktree에서 조회·추가·자동 적용을 검사한다."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import socketserver
import urllib.request
import sys
from contextlib import nullcontext
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def git(path, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    return subprocess.check_output(['git', '-C', str(path), *args], env=env, stderr=subprocess.STDOUT).decode().strip()


def repo(path):
    path.mkdir()
    git(path, 'init', '-q')
    git(path, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '--allow-empty', '-qm', 'fixture')
    return path


def skill(path):
    path.mkdir(parents=True)
    (path / 'SKILL.md').write_text('---\nname: sample\ndescription: fixture\n---\n')
    return str(path)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        os.environ['AGENT_HUD_HOME'] = str(base / 'hud')
        spec = importlib.util.spec_from_file_location('hud', ROOT / 'server.py')
        hud = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hud)
        main_repo = repo(base / 'main repo')
        wt = base / 'linked\nworktree'
        git(main_repo, 'worktree', 'add', '-q', '--detach', str(wt))
        other = repo(base / 'other')
        nested = repo(main_repo / 'nested')
        sub = main_repo / 'packages'; sub.mkdir()
        src = skill(base / 'sources' / 'sample')
        config = {'skills': [{'name': 'sample', 'source': src}], 'dirs': list(hud.GROUP_LINK_DIRS)}
        hud.skill_sources = lambda project: {'sample': src}
        hud.known_projects = lambda: [str(main_repo), str(wt)]

        # Existing status predicate must reject dead and wrong links.
        for rel in hud.GROUP_LINK_DIRS:
            p = wt / rel / 'sample'; p.parent.mkdir(parents=True); p.symlink_to(base / 'missing')
        assert not hud.skill_is_shared(str(wt), 'sample', src), 'dead links were reported shared'
        for rel in hud.GROUP_LINK_DIRS:
            p = wt / rel / 'sample'; p.unlink(); p.symlink_to(skill(base / rel.replace('/', '-') / 'other-sample'))
        assert not hud.skill_is_shared(str(wt), 'sample', src), 'wrong sources were reported shared'
        for rel in hud.GROUP_LINK_DIRS:
            p = wt / rel / 'sample'
            before = os.readlink(p)
            ok, _ = hud.link_skill('sample', True, str(wt))
            assert not ok and os.readlink(p) == before, 'existing foreign link was replaced'
            p.unlink()
        for rel in hud.GROUP_LINK_DIRS:
            p = wt / rel / 'sample'
            if p.is_symlink(): p.unlink()

        # Existence alone does not mean the HUD process can read the skill.
        for rel in hud.GROUP_LINK_DIRS:
            (wt / rel / 'sample').symlink_to(src)
        assert hud.skill_is_shared(str(wt), 'sample', src)
        md = Path(src) / 'SKILL.md'
        mode = md.stat().st_mode
        real_open = open
        def permission_denied(path, *args, **kwargs):
            if os.fspath(path) == str(md):
                raise PermissionError('unreadable fixture')
            return real_open(path, *args, **kwargs)
        md.chmod(0)
        try:
            # Root bypasses mode bits; simulate the same OS error in that case.
            with patch('builtins.open', permission_denied) if os.geteuid() == 0 else nullcontext():
                assert not hud.skill_is_shared(str(wt), 'sample', src), 'unreadable source was reported shared'
                assert not hud.preview_worktree_skills(str(main_repo), [str(wt)], config)['ok']
                assert not hud.apply_worktree_skills(str(main_repo), [str(wt)], config)['ok']
                assert hud._create_skill_link(str(main_repo), '.agents/skills', 'sample', src) == 'source_missing'
                assert not (main_repo / '.agents').exists(), 'unreadable source created target directories'
                assert all((wt / rel / 'sample').is_symlink() for rel in hud.GROUP_LINK_DIRS)
        finally:
            md.chmod(mode)
        assert hud.skill_is_shared(str(wt), 'sample', src), 'restored readable source was not shared'
        for rel in hud.GROUP_LINK_DIRS:
            (wt / rel / 'sample').unlink()

        identity = hud.git_repository(str(main_repo))
        assert identity['common_dir'] == hud.git_repository(str(wt))['common_dir']
        assert identity['common_dir'] != hud.git_repository(str(other))['common_dir']
        assert identity['common_dir'] != hud.git_repository(str(nested))['common_dir']
        rows = hud.git_worktrees(identity)
        assert {r['path'] for r in rows} == {str(main_repo), str(wt)}, rows
        assert next(r for r in rows if r['path'] == str(wt))['detached']
        assert hud.collect_worktrees(str(sub))['can_apply'] is False, 'subfolder config escaped to root'

        preview = hud.preview_worktree_skills(str(main_repo), [str(wt)], config)
        assert preview['ok'] and all(r['state'] == 'missing' for r in preview['rows']), preview
        # A change after preview is preserved during execution.
        actual = wt / '.agents/skills/sample'; actual.mkdir(); (actual / 'SKILL.md').write_text('user')
        result = hud.apply_worktree_skills(str(main_repo), [str(wt)], config)
        assert (actual / 'SKILL.md').read_text() == 'user'
        assert any(r['state'] == 'occupied' for r in result['rows'])
        assert (wt / '.claude/skills/sample').is_symlink()
        assert not (wt / '.claude/settings.local.json').exists()
        second = hud.apply_worktree_skills(str(main_repo), [str(wt)], config)
        assert not any(r['state'] == 'created' for r in second['rows'])
        assert not hud.preview_worktree_skills(str(main_repo), [str(other)], config)['ok']
        assert not hud.preview_worktree_skills(str(main_repo), [str(nested)], config)['ok']
        assert not hud.preview_worktree_skills(str(sub), [str(wt)], config)['ok']
        assert not hud.preview_worktree_skills(str(main_repo), [str(wt)],
            {'skills': [{'name': '../escape', 'source': src}], 'dirs': hud.GROUP_LINK_DIRS})['ok']
        assert not hud.preview_worktree_skills(str(main_repo), [str(wt)],
            {'skills': [{'name': 'sample', 'source': src}], 'dirs': ['../escape']})['ok']
        assert not hud.preview_worktree_skills(str(main_repo), [str(wt)],
            {'skills': [{'name': 'sample', 'source': str(base / 'unknown')}], 'dirs': hud.GROUP_LINK_DIRS})['ok']
        assert hud.local_path('/Volumes/unrequested/skills') is None
        nas = base / 'nas'; nas.symlink_to('/Volumes/unrequested')
        assert hud.local_path(str(nas / 'skills')) is None
        dead = base / 'removed'; git(main_repo, 'worktree', 'add', '-q', '--detach', str(dead))
        git(main_repo, 'worktree', 'remove', str(dead))
        assert not hud.apply_worktree_skills(str(main_repo), [str(dead)], config)['ok']
        assert not dead.exists()
        target = base / 'root-link'; git(main_repo, 'worktree', 'add', '-q', '--detach', str(target))
        outside = base / 'outside'; outside.mkdir()
        (target / '.agents').symlink_to(outside)
        only_agents = {**config, 'dirs': ['.agents/skills']}
        blocked = hud.apply_worktree_skills(str(main_repo), [str(target)], only_agents)
        assert any(r['state'] == 'blocked' for r in blocked['rows'])
        assert list(outside.iterdir()) == []
        racing = base / 'racing'; git(main_repo, 'worktree', 'add', '-q', '--detach', str(racing))
        open_real = hud.os.open
        def replace_parent(path, flags, *args, **kwargs):
            if path == str(racing) and not (racing / '.agents').exists():
                (racing / '.agents').symlink_to(outside)
            return open_real(path, flags, *args, **kwargs)
        hud.os.open = replace_parent
        try:
            raced = hud.apply_worktree_skills(str(main_repo), [str(racing)], only_agents)
            assert any(r['state'] == 'blocked' for r in raced['rows'])
            assert list(outside.iterdir()) == []
        finally:
            hud.os.open = open_real
        dead_src = base / 'sources/dead'; dead_src.symlink_to(base / 'missing')
        hud.skill_sources = lambda project: {'sample': src, 'dead': str(dead_src)}
        missing_src_config = {'skills': [{'name': 'dead', 'source': str(dead_src)}], 'dirs': config['dirs']}
        assert not hud.preview_worktree_skills(str(main_repo), [str(wt)], missing_src_config)['ok']

        # Real HTTP requests validate source/target identity and return per-entry results.
        with socketserver.ThreadingTCPServer(('127.0.0.1', 0), hud.Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            url = 'http://127.0.0.1:' + str(server.server_address[1]) + '/api/worktrees'
            def request(payload):
                req = urllib.request.Request(url, data=json.dumps(payload).encode(), method='POST')
                with urllib.request.urlopen(req) as response:
                    return json.load(response)
            p = {'project': str(main_repo), 'action': 'preview', 'targets': [str(wt)], 'config': config}
            assert request(p)['ok']
            assert not request({**p, 'targets': [str(other)]})['ok']
            assert not request({**p, 'project': str(sub)})['ok']
            assert not request({**p, 'action': 'apply', 'targets': [str(dead)]})['ok']
            assert not dead.exists()
            server.shutdown(); worker.join()

        # Automatic application is opt-in; enabling it does not alter existing checkouts.
        assert hud.set_worktree_policy(str(main_repo), config, True)['ok']
        hud.auto_apply_worktrees_once()
        assert not (main_repo / '.agents').exists()
        new = base / 'new'; git(main_repo, 'worktree', 'add', '-q', '--detach', str(new))
        hud.auto_apply_worktrees_once()
        assert (new / '.agents/skills/sample/SKILL.md').is_file()
        ledger = hud.read_json(hud.WORKTREE_FILE)
        assert str(new / '.agents/skills/sample') in ledger['links']
        assert str(wt / '.agents/skills/sample') not in ledger['links'], 'user directory claimed'
        assert not hud.read_json(hud.SETS_FILE), 'skill sharing changed group assignment'
        hud.auto_apply_worktrees_once()
        assert (new / '.agents/skills/sample').is_symlink()
        # Foreign replacement stays intact on subsequent automatic polls.
        (new / '.agents/skills/sample').unlink(); (new / '.agents/skills/sample').symlink_to(base / 'missing')
        hud.auto_apply_worktrees_once()
        assert os.readlink(new / '.agents/skills/sample') == str(base / 'missing')
        assert hud.set_worktree_override(str(main_repo), str(new), 'exclude')['ok']
        (new / '.claude/skills/sample').unlink()
        hud.auto_apply_worktrees_once()
        assert not (new / '.claude/skills/sample').exists()
        assert hud.set_worktree_override(str(main_repo), str(new), 'custom', only_agents)['ok']
        hud.auto_apply_worktrees_once()
        assert not (new / '.claude/skills/sample').exists()
        other_src = skill(base / 'sources/other')
        hud.skill_sources = lambda project: {'sample': src, 'other': other_src}
        custom = {'skills': [{'name': 'other', 'source': other_src}], 'dirs': ['.agents/skills']}
        assert hud.set_worktree_override(str(main_repo), str(new), 'custom', custom)['ok']
        hud.auto_apply_worktrees_once()
        assert (new / '.agents/skills/other/SKILL.md').is_file()
        assert not (new / '.claude/skills/other').exists()
        assert (new / '.agents/skills/sample').is_symlink(), 'custom config deleted extra skill'
        assert not hud.set_worktree_override(str(main_repo), str(other), 'exclude')['ok']
        # The setup command applies the pinned custom config even without a server.
        env = dict(os.environ, AGENT_HUD_HOME=hud.TOOL_DIR, HOME=str(base / 'fake-home'))
        command = [sys.executable, str(ROOT / 'server.py'), 'worktrees']
        listed = subprocess.run(command + [str(main_repo)], env=env, capture_output=True, text=True)
        assert listed.returncode == 0 and str(new) in listed.stdout, listed.stderr
        (new / '.agents/skills/other').unlink()
        applied = subprocess.run(command + ['apply', str(new)], env=env, capture_output=True, text=True)
        assert applied.returncode == 0, applied.stderr + applied.stdout
        assert (new / '.agents/skills/other').is_symlink()
        assert hud.set_worktree_override(str(main_repo), str(new), 'exclude')['ok']
        excluded = subprocess.run(command + ['apply', str(new)], env=env, capture_output=True, text=True)
        assert excluded.returncode != 0
        assert hud.set_worktree_policy(str(main_repo), config, False)['ok']
        later = base / 'later'; git(main_repo, 'worktree', 'add', '-q', '--detach', str(later))
        hud.auto_apply_worktrees_once()
        assert not (later / '.agents').exists()
        assert not (new / '.claude/settings.local.json').exists()
        state = hud.collect_worktrees(str(main_repo))
        assert str(later) in {r['path'] for r in state['rows']}
        assert state['enabled'] is False
        # A deleted checkout remains informational only, including on the next poll.
        git(main_repo, 'worktree', 'remove', '--force', str(new))
        hud.auto_apply_worktrees_once()
        assert not new.exists()
        print('PASS (real Git worktrees, preservation, manual and automatic application)')


if __name__ == '__main__':
    main()
