"""업데이트 알림은 실제로 업데이트되는 길로 이어져야 한다.
- git 설치본은 에이전트에게 보낼 문장을 복사해 주고, 그 문장은 README의 한 절을 가리킨다.
  그 절이 없거나 방법이 빠지면 에이전트가 엉뚱하게 업데이트한다. 서비스는
  ~/.claude/tools/agent-hud/에 복사된 server.py를 돌리므로 git pull만으로는 안 바뀐다.
- Homebrew 설치본인지는 server.py가 놓인 경로로 가린다. 잘못 가리면 git 설치본에
  brew 버튼이 뜨거나 brew 설치본이 복사 문장만 받는다.
   python3 tests/test_update_hint.py"""
import importlib.util, os, re, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def anchor(heading):
    return re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")


def check_prompt():
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    prompts = re.findall(r"update_prompt: \(latest, repo\) => `([^`]*)`", src)
    assert len(prompts) == 2, f"en/ko 업데이트 문장을 못 찾았다: {len(prompts)}개"
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    sections = {anchor(h): body for h, body in re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", readme, re.M | re.S)}
    for p in prompts:
        m = re.search(r"#([a-z0-9-]+)", p)
        assert m, f"README 절을 가리키지 않는다: {p}"
        body = sections.get(m.group(1))
        assert body is not None, f"README에 #{m.group(1)} 절이 없다"
        assert "brew upgrade agent-hud" in body, "README 업데이트 절에 Homebrew 방법이 없다"
        assert "./install.sh" in body and "git pull" in body, "README 업데이트 절에 git 설치본 방법이 없다"


def check_brew_prefix():
    with tempfile.TemporaryDirectory() as d:
        d = os.path.realpath(d)
        lib = os.path.join(d, "Cellar", "agent-hud", "0.3.0", "libexec")
        os.makedirs(lib); os.makedirs(os.path.join(d, "bin"))
        server = os.path.join(lib, "server.py"); open(server, "w").close()
        assert hud.brew_prefix(server) is None, "brew가 없는데 Homebrew 설치로 봤다"
        open(os.path.join(d, "bin", "brew"), "w").close()
        assert hud.brew_prefix(server) == d, "Homebrew 설치본을 못 알아봤다"
        clone = os.path.join(d, "tools", "agent-hud", "server.py")
        os.makedirs(os.path.dirname(clone)); open(clone, "w").close()
        assert hud.brew_prefix(clone) is None, "git 설치본을 Homebrew로 봤다"
        other = os.path.join(d, "Cellar", "some-tool", "1.0", "server.py")
        os.makedirs(os.path.dirname(other)); open(other, "w").close()
        assert hud.brew_prefix(other) is None, "다른 formula 안의 파일을 agent-hud로 봤다"


def main():
    check_prompt()
    check_brew_prefix()
    print("PASS")


if __name__ == "__main__":
    main()
