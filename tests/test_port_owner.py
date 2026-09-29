"""대시보드 포트에 다른 프로그램이 떠 있으면 Agent HUD로 치지 않는다.
열려 있기만 하면 '이미 떠 있다'고 보고 끝내던 때, 옛 설치본이 쓰던 7717을 다른 대시보드가
물려받자 새 서버가 뜨자마자 끝나기를 반복했다.
   python3 tests/test_port_owner.py"""
import http.server, importlib.util, os, socketserver, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


def serve(handler):
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Other(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><title>something else</title>"
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass


def main():
    other = serve(Other)
    port = other.server_address[1]
    assert not hud.hud_alive(port), "다른 프로그램을 Agent HUD로 봤다"
    other.shutdown()

    me = serve(hud.Handler)
    assert hud.hud_alive(me.server_address[1]), "Agent HUD를 못 알아봤다"
    me.shutdown()
    print("PASS")


if __name__ == "__main__":
    main()
