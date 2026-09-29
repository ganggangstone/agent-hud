"""packaging/Agent HUD.app이 앱으로 열릴 수 있는 모양인지 본다. cask가 이 폴더를 그대로
/Applications에 옮기므로, 여기서 깨지면 사용자는 아무 반응 없는 아이콘을 받는다.
실제로 눌렀을 때 열리는지는 macOS에서 직접 열어 봐야 안다.
   python3 tests/test_mac_app.py"""
import os, plistlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "packaging", "Agent HUD.app", "Contents")


def main():
    with open(os.path.join(APP, "Info.plist"), "rb") as f:
        info = plistlib.load(f)
    assert info.get("CFBundlePackageType") == "APPL", "앱 종류(APPL)가 아니다"
    exe = os.path.join(APP, "MacOS", info["CFBundleExecutable"])
    assert os.path.isfile(exe), f"실행 파일이 없다: {exe}"
    assert os.access(exe, os.X_OK), "실행 권한이 없다 (git에 +x로 올라갔는지 확인)"
    assert "agent-hud" in open(exe).read() and " open" in open(exe).read(), "agent-hud open을 부르지 않는다"
    icon = info.get("CFBundleIconFile", "")
    assert os.path.isfile(os.path.join(APP, "Resources", icon + ".icns")), f"아이콘 파일이 없다: {icon}"
    print("PASS")


if __name__ == "__main__":
    main()
