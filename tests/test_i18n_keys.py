"""화면이 부르는 i18n 키가 en/ko 양쪽에 다 있는지 본다.
   `t().foo`를 부르는데 키가 없으면 그 자리에서 TypeError가 나고 화면이 멈추는데,
   파이썬 테스트도 `node --check`도 전부 통과한다 -- 문법은 멀쩡하기 때문이다.
   실제로 키 하나를 지웠다가 나중에 다시 쓰는 사고가 있었다(badge_off_tip).
   python3 tests/test_i18n_keys.py"""
import importlib.util, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def tables(page):
    """const T = { en: {...}, ko: {...} } 에서 언어별 최상위 키를 뽑는다."""
    body = re.search(r"const T = \{(.*?)\n\};", page, re.S)
    assert body, "PAGE에서 const T를 못 찾았다"
    body = body.group(1)
    assert "\n  ko: {" in body, "ko 블록을 못 찾았다"
    en, ko = body.split("\n  ko: {", 1)
    # 한 줄에 키가 둘씩 있는 자리가 있다(`set_apply: '..', set_applied: '..'`).
    # 줄머리만 보면 놓치므로 여는 괄호나 쉼표 뒤도 같이 본다. 문자열 안의
    # 콜론(`'group: '`)은 따옴표가 앞에 와서 걸리지 않는다.
    key = lambda b: set(re.findall(r"(?:^|[,{])\s*([a-z_][a-z0-9_]*)\s*:", b, re.M))
    return key(en) - {"en"}, key(ko) - {"ko"}


def main():
    page = hud.PAGE
    en, ko = tables(page)
    assert en, "en 키를 하나도 못 뽑았다 (정규식이 낡았다)"

    only_en, only_ko = sorted(en - ko), sorted(ko - en)
    assert not only_en, f"ko에 없는 키: {only_en}"
    assert not only_ko, f"en에 없는 키: {only_ko}"

    # 화면이 실제로 부르는 키. t().foo 와 t().foo(...) 둘 다 잡는다.
    used = set(re.findall(r"\bt\(\)\.([a-z_][a-z0-9_]*)", page))
    missing = sorted(used - en)
    assert not missing, f"화면이 부르는데 T에 없는 키: {missing}"

    # 함수인지 문자열인지가 언어별로 다르면 한쪽 언어에서만 터진다.
    fn = lambda b: set(re.findall(r"^\s{2,4}([a-z_][a-z0-9_]*)\s*:\s*\(?[a-z0-9, ]*\)?\s*=>", b, re.M))
    body = re.search(r"const T = \{(.*?)\n\};", page, re.S).group(1)
    e, k = body.split("\n  ko: {", 1)
    diff = sorted(fn(e) ^ fn(k))
    assert not diff, f"en/ko에서 함수/문자열이 갈린 키: {diff}"

    print(f"PASS (키 {len(en)}개, 화면에서 부르는 키 {len(used)}개)")


if __name__ == "__main__":
    main()
