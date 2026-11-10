import sys, json, time
sys.path.insert(0, "/home/claude/audit/harness")
from audit_lib import Lab
root, rid, key, go_at, n = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), int(sys.argv[5])
lb = Lab(root=root)
while time.time() < go_at: pass
print(json.dumps([lb.book(rid, key) for _ in range(n)]))
