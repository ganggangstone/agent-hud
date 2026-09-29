"""세션 여러 개가 한꺼번에 등록해도 프로젝트 목록이 깨지거나 비지 않는다."""
import json, os, sys, tempfile, threading

os.environ["AGENT_HUD_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server

server.remove_stale_skill_denies = lambda p: None
seed = {f"/seed/{i}": i for i in range(40)}
server.write_json(server.PROJECTS_FILE, seed)

for r in range(30):
    ts = [threading.Thread(target=f, args=(f"/p/{r}/{i}",))
          for i, f in enumerate([server.register_project, server.remember_project] * 4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    with open(server.PROJECTS_FILE) as fh:
        data = json.load(fh)                    # 깨졌으면 여기서 실패한다
    assert set(seed) <= set(data), f"round {r}: {40 - len(set(seed) & set(data))} lost"
    assert all(f"/p/{r}/{i}" in data for i in range(8)), f"round {r}: new entry lost"
print("ok")
