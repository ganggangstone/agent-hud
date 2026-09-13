"""페이지에 실린 자바스크립트가 문법적으로 성립하는지 본다.
   여기가 깨지면 대시보드는 200을 돌려주고 헤더만 그린 채 아무것도 안 나온다 --
   파이썬 테스트도 curl도 전부 통과하므로 이 검사가 없으면 아무도 못 잡는다.
   python3 tests/test_page_js.py"""
import importlib.util, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def main():
    node = shutil.which("node")
    if not node:
        print("SKIP (node 없음)")
        return
    blocks = re.findall(r"<script>(.*?)</script>", hud.PAGE, re.S)
    assert blocks, "PAGE에 <script>가 없다"
    for i, js in enumerate(blocks):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(js)
            path = f.name
        try:
            r = subprocess.run([node, "--check", path], capture_output=True, text=True)
            assert r.returncode == 0, f"script[{i}] 문법 오류:\n{r.stderr}"
        finally:
            os.unlink(path)
    print(f"PASS ({len(blocks)} script block)")


if __name__ == "__main__":
    main()
