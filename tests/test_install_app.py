"""'앱으로 설치' 버튼이 쓰는 /manifest.json, /icon.png가 유효한지 본다.
   실제 설치 가능 여부(Chrome의 beforeinstallprompt)는 브라우저에서만 확인할 수 있다 --
   여기서는 매니페스트 필드와 PNG 형식만 본다.
   python3 tests/test_install_app.py"""
import importlib.util, json, os, struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server.py")

spec = importlib.util.spec_from_file_location("hud", SERVER)
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def main():
    manifest = json.loads(hud.MANIFEST_JSON)
    assert manifest["display"] == "standalone", "standalone이 아니면 브라우저 탭으로 열린다"
    assert manifest["start_url"] == "/"
    icons = manifest["icons"]
    assert icons and icons[0]["src"] == "/icon.png", "서버가 실제로 내려주는 경로와 달라야 하는 이유가 없다"

    png = hud.ICON_PNG
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "PNG 시그니처가 아니다"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (512, 512), f"아이콘 크기가 매니페스트와 달라야 하는 이유가 없다: {width}x{height}"

    # 페이지가 매니페스트를 실제로 참조하는지 (버튼만 있고 링크가 없으면 설치 조건이 안 잡힌다)
    assert '<link rel="manifest" href="/manifest.json">' in hud.PAGE

    print("PASS")


if __name__ == "__main__":
    main()
