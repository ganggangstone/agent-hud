"""랜딩 페이지(docs/index.html, docs/ko/index.html)가 최소한 깨지진 않는지 본다.
   실제 디자인 판단은 사람이 본다 -- 여기서는 기계적으로 잡히는 것만.
   python3 tests/test_landing.py"""
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = [
    os.path.join(ROOT, "docs", "index.html"),
    os.path.join(ROOT, "docs", "ko", "index.html"),
]


def check_js(path, html):
    """인라인 <script>가 문법적으로 깨졌으면 여기서 잡는다 -- 제품 쪽에서
    실제로 이 검사가 없어서 화면이 헤더만 그리고 멈춘 사고가 났었다.
    JSON-LD는 자바스크립트가 아니므로 node가 아니라 JSON으로 읽는다 --
    한 덩어리로 묶어 node에 넘기면 멀쩡한 구조화 데이터가 문법 오류로 잡힌다."""
    scripts = re.findall(r"<script(\s[^>]*)?>(.*?)</script>", html, re.S)
    assert scripts, f"{path}: <script> 블록이 없다"
    ld_seen = False
    for i, (attrs, code) in enumerate(scripts):
        if "application/ld+json" in (attrs or ""):
            ld_seen = True
            try:
                data = json.loads(code)
            except json.JSONDecodeError as e:
                raise AssertionError(f"{path} JSON-LD: {e}")
            assert data.get("@context") == "https://schema.org", f"{path}: JSON-LD @context가 없다"
            assert data.get("@type"), f"{path}: JSON-LD @type이 없다"
            continue
        out = subprocess.run(["node", "--check"], input=code, capture_output=True, text=True)
        assert out.returncode == 0, f"{path} script #{i}: {out.stderr}"
    assert ld_seen, f"{path}: JSON-LD 구조화 데이터가 빠졌다"


def check_images(path, html, base_dir):
    for m in re.finditer(r'<img[^>]+src="([^"]+)"', html):
        src = m.group(1)
        if src.startswith("http"):
            continue
        full = os.path.normpath(os.path.join(base_dir, src))
        assert os.path.isfile(full), f"{path}: 없는 이미지 참조 {src}"


def check_hreflang(path, html):
    assert 'hreflang="en"' in html and 'hreflang="ko"' in html and 'hreflang="x-default"' in html, \
        f"{path}: hreflang alternate 태그가 빠졌다"


def main():
    for path in PAGES:
        with open(path, encoding="utf-8") as f:
            html = f.read()
        check_js(path, html)
        check_images(path, html, os.path.dirname(path))
        check_hreflang(path, html)
    print("PASS")


if __name__ == "__main__":
    main()
