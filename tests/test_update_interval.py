"""업데이트 확인이 서버 재시작과 상관없이 하루에 한 번만 나가는지 본다.
   예전에는 서버가 켜질 때마다(로그인, launchd 재시작, 훅이 새로 띄울 때) 곧바로 한 번 더
   확인했다. 이제는 마지막으로 확인한 시각에서 하루가 지나야 확인한다.
   python3 tests/test_update_interval.py"""
import importlib.util, json, os, shutil, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)
DAY = hud.UPDATE_CHECK_INTERVAL_SEC


def main():
    tmp = tempfile.mkdtemp()
    hud.UPDATE_CACHE_FILE = os.path.join(tmp, ".update_check.json")
    now = 1_800_000_000
    try:
        def cache(checked_at):
            with open(hud.UPDATE_CACHE_FILE, "w") as f:
                json.dump({"latest": "0.2.0", "checked_at": checked_at}, f)

        assert hud._update_wait(now) == 0, "처음 켤 때는 바로 확인한다"
        cache(now - 3600)
        assert hud._update_wait(now) == DAY - 3600, "한 시간 전에 확인했으면 23시간 뒤"
        cache(now - 2 * DAY)
        assert hud._update_wait(now) == 0, "하루가 지났으면 바로"
        cache(now + 5 * DAY)                              # 시계가 뒤로 간 경우
        assert hud._update_wait(now) == DAY, "하루보다 오래 기다리지 않는다"
    finally:
        shutil.rmtree(tmp)
    print("ok")


if __name__ == "__main__":
    main()
