"""목록에서 뺀 프로젝트만 사라지고, 폴더와 다른 항목은 그대로 남는다."""
import os, sys, tempfile

os.environ["AGENT_HUD_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server

server.remove_stale_skill_denies = lambda p: None
a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
server.register_project(a)
server.register_project(b)

server.unregister_project(a)
assert server.known_projects() == [b], server.known_projects()
assert os.path.isdir(a)                   # 폴더는 건드리지 않는다
server.unregister_project("/not/listed")  # 없는 항목은 조용히 넘어간다
assert server.known_projects() == [b]
print("ok")
