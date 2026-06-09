"""
E2E verification script for Ant Colony four-module system.
Tests: Gateway → Agent → Memory (Warm/Cold) → Knowledge pipeline.
"""
import json
import sys
import time
import urllib.request
import urllib.error

GATEWAY = "http://10.12.254.122:18090"
GBRAIN = "http://10.12.254.122:8787"
HINDSIGHT = "http://10.12.254.122:8890"

EMBED = "http://10.12.254.122:8766"

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} — {detail}")


def api_get(url: str):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def api_post(url: str, data: dict):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def api_post_raw(url: str, data: dict):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=5).getcode()


# === L1: Gateway ===
print("\n=== L1: Gateway (:18090) ===")
try:
    r = api_get(f"{GATEWAY}/health")
    check("Gateway health", r.get("status") == "healthy", str(r))
except Exception as e:
    check("Gateway health", False, str(e))

try:
    r = api_post_raw(GATEWAY, {"from": "e2e-test", "content": "E2E test message", "space_id": "e2e-proj"})
    check("Message ingest", r == 200, f"HTTP {r}")
except Exception as e:
    check("Message ingest", False, str(e))

try:
    r = api_get(f"{GATEWAY}/tasks?space_id=e2e-proj")
    check("Task list", "tasks" in r, f"{len(r.get('tasks',[]))} tasks")
except Exception as e:
    check("Task list", False, str(e))

# === L2: gbrain (Cold) ===
print("\n=== L2: gbrain Cold Layer (:8787) ===")
try:
    r = api_get(f"{GBRAIN}/health")
    check("gbrain health", r.get("status") == "healthy", str(r))
except Exception as e:
    check("gbrain health", False, str(e))

try:
    r = api_post(f"{GBRAIN}/mcp", {
        "method": "put_page",
        "params": {"id": "e2e-page", "title": "E2E Test", "content": "Test content for verification", "tags": ["e2e"]},
        "id": 1,
    })
    check("gbrain put_page", r.get("result", {}).get("status") == "ok", str(r))
except Exception as e:
    check("gbrain put_page", False, str(e))

try:
    r = api_post(f"{GBRAIN}/mcp", {
        "method": "get_page",
        "params": {"id": "e2e-page"},
        "id": 2,
    })
    check("gbrain get_page", r.get("result") is not None, str(r)[:100])
except Exception as e:
    check("gbrain get_page", False, str(e))

# === L2: Hindsight (Warm) ===
print("\n=== L3: Hindsight Warm Layer (:8890) ===")
try:
    r = api_get(f"{HINDSIGHT}/health")
    check("Hindsight health", r.get("status") == "healthy", str(r))
except Exception as e:
    check("Hindsight health", False, str(e))

try:
    r = api_post(f"{HINDSIGHT}/v1/default/banks/hermes/memories", {
        "id": "e2e-mem-1", "memory": "E2E verification memory entry with keywords",
        "tags": ["e2e", "test"],
    })
    check("Hindsight retain", r.get("status") == "retained", str(r))
except Exception as e:
    check("Hindsight retain", False, str(e))

try:
    r = api_get(f"{HINDSIGHT}/v1/default/banks/hermes/memories/recall?query=verification&limit=5")
    check("Hindsight recall", r.get("count", 0) >= 1, f"found {r.get('count',0)}")
except Exception as e:
    check("Hindsight recall", False, str(e))

try:
    r = api_get(f"{HINDSIGHT}/v1/default/banks/hermes/stats")
    check("Hindsight stats", "total_memories" in r, str(r))
except Exception as e:
    check("Hindsight stats", False, str(e))

# === L4: Embedding ===
print("\n=== L4: Embedding (:8766) ===")
try:
    r = api_get(f"{EMBED}/health")
    check("Embed health", r.get("status") == "healthy", str(r))
except Exception as e:
    check("Embed health", False, str(e))
try:
    data = json.dumps({"texts": ["test"]}).encode()
    req = urllib.request.Request(f"{EMBED}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        r = json.loads(resp.read())
    check("Embed encode", len(r.get("embeddings", [])) == 1, f"dim={r.get('dim')}")
except Exception as e:
    check("Embed encode", False, str(e))

# Summary
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
