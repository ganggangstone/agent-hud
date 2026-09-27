"""설정 파일이 JSON 객체가 아닐 때 대시보드 전체가 죽지 않는지 본다.
   read_json은 파싱 실패만 빈 값으로 바꾸고 있어서, 파일 내용이 [] 나 "x" 처럼 형식은 맞지만
   객체가 아니면 그대로 돌려줬고, 뒤따르는 .get()에서 /api/state 전체가 실패했다.
   python3 tests/test_read_json.py"""
import importlib.util, json, os, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def main():
    tmp = tempfile.mkdtemp()
    try:
        for bad in ([], "x", 3, None):
            p = os.path.join(tmp, "f.json")
            with open(p, "w") as f:
                json.dump(bad, f)
            assert hud.read_json(p) == {}, (bad, hud.read_json(p))
            assert hud.read_json(p, {"k": 1}) == {"k": 1}, bad

        proj = os.path.join(tmp, "proj")
        os.makedirs(os.path.join(proj, ".claude"))
        for name in ("settings.json", "settings.local.json"):
            with open(os.path.join(proj, ".claude", name), "w") as f:
                f.write("[]")
        state = hud.build_state(proj)                     # 여기서 AttributeError가 나던 자리
        assert len(state["panels"]) >= 3, state.keys()
    finally:
        shutil.rmtree(tmp)
    print("ok")


if __name__ == "__main__":
    main()
