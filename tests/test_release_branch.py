"""dev pushes run checks; release guard executes against real temporary Git history."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    checks = (ROOT / '.github/workflows/test.yml').read_text()
    branches = re.search(r'branches:\s*\[([^]]+)\]', checks)
    assert branches and {'main', 'dev'} <= {s.strip() for s in branches[1].split(',')}
    workflow = (ROOT / '.github/workflows/release.yml').read_text()
    guard = re.search(r'      - name: 배포 브랜치에 반영된 커밋인지\n        run: \|\n((?:          .*\n)+)', workflow)
    assert guard, 'release does not verify main membership'
    script = '\n'.join(line[10:] for line in guard[1].splitlines())
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_AUTHOR_NAME='Fixture', GIT_COMMITTER_NAME='Fixture',
                   GIT_AUTHOR_EMAIL='fixture@example.invalid', GIT_COMMITTER_EMAIL='fixture@example.invalid')
        def git(*args):
            return subprocess.check_output(['git', '-C', str(base), *args], env=env, stderr=subprocess.STDOUT).decode().strip()
        git('init', '-q', '-b', 'main')
        git('commit', '--allow-empty', '-qm', 'main fixture')
        main_sha = git('rev-parse', 'HEAD')
        remote = base / 'remote.git'
        git('init', '-q', '--bare', str(remote))
        git('remote', 'add', 'origin', str(remote))
        git('push', '-q', 'origin', 'main')
        git('switch', '-qc', 'dev')
        git('commit', '--allow-empty', '-qm', 'dev fixture')
        dev_sha = git('rev-parse', 'HEAD')
        def run(sha):
            return subprocess.run(['bash', '-c', script], cwd=base,
                                  env=dict(env, GITHUB_SHA=sha), capture_output=True, text=True)
        assert run(main_sha).returncode == 0, 'main commit rejected'
        assert run(dev_sha).returncode != 0, 'unmerged dev commit could be released'
        git('push', '-q', 'origin', 'dev:main')
        assert run(dev_sha).returncode == 0, 'merged release commit rejected'
        print('PASS (dev checks, unmerged dev release rejected, main release allowed)')


if __name__ == '__main__':
    main()
