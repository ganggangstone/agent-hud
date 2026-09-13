"""업데이트 알림은 실제로 업데이트되는 방법을 안내해야 한다.
서비스는 ~/.claude/tools/agent-hud/에 복사된 server.py를 실행하므로 git pull만으로는 안 바뀐다.
   python3 tests/test_update_hint.py"""
import os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    hints = re.findall(r"update_available: \(v, latest, repo\) => `([^`]*)`", src)
    assert len(hints) == 2, f"en/ko 업데이트 문구를 못 찾았다: {len(hints)}개"
    for h in hints:
        assert "install.sh" in h, f"install.sh 재실행 안내가 없다: {h}"
        assert "brew upgrade" in h, f"Homebrew 설치본 안내가 없다: {h}"
    print("PASS")


if __name__ == "__main__":
    main()
