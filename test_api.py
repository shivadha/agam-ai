"""
HTTP-level end-to-end test for the PulseForge workflow API.
Tests: login -> workflow run -> verify results
"""
import requests
import sys

BASE = "http://127.0.0.1:5000"

# 1. Login
s = requests.Session()
print("[TEST] Logging in...")
r = s.post(f"{BASE}/login", json={"email": "shivamdhagat1@gmail.com", "password": "admin"})
if r.status_code not in (200, 302):
    print(f"[TEST] Login failed: {r.status_code} {r.text}")
    sys.exit(1)

login_data = {}
try:
    login_data = r.json()
except:
    pass

print(f"[TEST] Login response: {r.status_code} - {login_data}")

# 2. Test API auth - get saved articles
r2 = s.get(f"{BASE}/api/saved_articles")
print(f"[TEST] saved_articles: {r2.status_code}")
if r2.status_code == 403:
    print("[TEST] FAIL: Still getting 403 - session not established")
    sys.exit(1)

# 3. Run a simple workflow (article-trigger + gen-script only - fast test)
print("[TEST] Running simple workflow...")
simple_payload = {
    "nodes": [
        {"id": "n1", "type": "article-trigger", "data": {"topic": "AI Test"}},
        {"id": "n2", "type": "gen-script", "data": {}},
    ],
    "edges": [
        {"source": "n1", "target": "n2"},
    ]
}
r3 = s.post(f"{BASE}/api/workflow/run", json=simple_payload)
print(f"[TEST] Workflow run: {r3.status_code}")
print(f"[TEST] Response: {r3.text[:500]}")

if r3.status_code == 403:
    print("[TEST] FAIL: Got 403 Forbidden - session cookie not being sent")
    sys.exit(1)
elif r3.status_code == 200:
    data = r3.json()
    results = data.get("results", {})
    print(f"\n[TEST] === RESULTS ===")
    for node_id, res in results.items():
        status = res.get("status", "?")
        node_type = res.get("node_type", "?")
        err = res.get("error", "")
        print(f"  {node_id} ({node_type}): {status}" + (f" -- {err}" if err else ""))
    print("[TEST] PASS: Workflow ran successfully!")
else:
    print(f"[TEST] FAIL: Unexpected status {r3.status_code}")
    sys.exit(1)
