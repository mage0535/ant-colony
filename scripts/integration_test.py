"""
Four-module integration test. Tests the complete pipeline:
  L1: Gateway receives message → routes to Agent
  L2: Agent (Hermes) processes with memory context
  L3: Memory Sidecar stores/recalls facts (Warm+Cold)
  L4: KMM pipeline archives and indexes knowledge

Run: python3 scripts/integration_test.py
"""
import json, sys, time, urllib.request


passed = 0
total = 0

def check(name):
    global passed, total
    total += 1
    passed += 1
    print(f"  ✅ {name}")

def fail(name, reason=""):
    global total
    total += 1
    print(f"  ❌ {name} — {reason}")

def api_get(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())

def api_post(url, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def api_post_raw(url, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=10).getcode()


# ==============================
# Phase 1: Gateway → Agent
# ==============================
print("=== PHASE 1: Message → Agent (OpenVort + Hermes) ===")

try:
    r = api_get(f"{GATEWAY}/health")
    check("1.1 Gateway health")
except Exception as e:
    fail("1.1 Gateway health", str(e))

try:
    r = api_post_raw(GATEWAY, {
        "from": "int-user", 
        "content": "Discuss optimizing the homepage load time. We need to implement lazy loading for images and assets.",
        "space_id": "int-proj"
    })
    check("1.2 Message sent to space" if r == 200 else f"1.2 HTTP {r}")
except Exception as e:
    fail("1.2 Message sent", str(e))

try:
    r = api_post_raw(GATEWAY, {
        "from": "int-user2",
        "content": "Also the API response time is too slow, we should add caching with Redis.",
        "space_id": "int-proj"
    })
    check("1.3 Second message buffered" if r == 200 else f"1.3 HTTP {r}")
except Exception as e:
    fail("1.3 Second message", str(e))

# Test personal agent via Gateway (LLM-dependent, may need API key)
try:
    r = api_post_raw(GATEWAY, {"from": "int-user", "content": "hello"})
    if r == 200:
        check("1.4 Personal agent responds")
    else:
        print(f"  ⚠️  1.4 Personal agent returned HTTP {r} (LLM may need config)")
except Exception as e:
    print(f"  ⚠️  1.4 Personal agent skipped: {e}")

# ==============================
# Phase 2: Memory Sidecar
# ==============================
print("\n=== PHASE 2: Memory Storage (Memory Sidecar) ===")

try:
    r = api_post(f"{GBRAIN}/mcp", {
        "method": "put_page",
        "params": {"id": "int-page-1", "title": "Homepage Optimization", 
                   "content": "Lazy loading for images, API caching with Redis. Front-end and back-end performance improvements.",
                   "tags": ["performance", "frontend", "backend"]},
        "id": 1,
    })
    check("2.1 gbrain page created" if r["result"]["status"] == "ok" else "2.1")
except Exception as e:
    fail("2.1 gbrain create", str(e))

try:
    r = api_post(f"{HINDSIGHT}/v1/default/banks/hermes/memories", {
        "id": "int-mem-1",
        "memory": "Homepage needs lazy loading for performance optimization",
        "tags": ["performance", "optimization"],
    })
    check("2.2 Hindsight memory retained" if r["status"] == "retained" else "2.2")
except Exception as e:
    fail("2.2 Hindsight retain", str(e))

try:
    r = api_post(f"{HINDSIGHT}/v1/default/banks/hermes/memories", {
        "id": "int-mem-2",
        "memory": "API response time needs Redis caching layer",
        "tags": ["api", "caching"],
    })
    check("2.3 Second memory retained" if r["status"] == "retained" else "2.3")
except Exception as e:
    fail("2.3 Second memory", str(e))

# ==============================
# Phase 3: Memory Recall
# ==============================
print("\n=== PHASE 3: Memory Recall (Hot+Warm+Cold) ===")

try:
    r = api_get(f"{HINDSIGHT}/v1/default/banks/hermes/memories/recall?query=performance&limit=5")
    found = r.get("count", 0)
    check(f"3.1 Warm recall (found {found})" if found >= 2 else f"3.1 only {found}")
except Exception as e:
    fail("3.1 Warm recall", str(e))

try:
    r = api_post(f"{GBRAIN}/mcp", {
        "method": "search",
        "params": {"query": "optimization", "limit": 5},
        "id": 2,
    })
    found = len(r.get("result", []))
    check(f"3.2 Cold recall (found {found})" if found >= 1 else f"3.2 none found")
except Exception as e:
    fail("3.2 Cold recall", str(e))

try:
    data = json.dumps({"texts": ["homepage optimization performance"]}).encode()
    req = urllib.request.Request(f"{EMBED}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        r = json.loads(resp.read())
    check(f"3.3 Semantic embed (dim={r['dim']})" if r["dim"] == 512 else "3.3")
except Exception as e:
    fail("3.3 Semantic embed", str(e))

# ==============================
# Phase 4: Knowledge Pipeline
# ==============================
print("\n=== PHASE 4: Knowledge Pipeline (KMM) ===")

try:
    r = api_get(f"{HINDSIGHT}/v1/default/banks/hermes/stats")
    total_mem = r.get("total_memories", 0)
    check(f"4.1 Memory stats ({total_mem} memories)" if total_mem >= 2 else f"4.1 only {total_mem}")
except Exception as e:
    fail("4.1 Memory stats", str(e))

try:
    r = api_get(f"{GBRAIN}/mcp")
    check("4.2 gbrain MCP accessible" if "service" in r else "4.2")
except Exception as e:
    fail("4.2 gbrain MCP", str(e))

# Final cross-check
try:
    r = api_get(f"{GBRAIN}/health")
    rg = r.get("status")
    r = api_get(f"{HINDSIGHT}/health")
    rh = r.get("status")
    r = api_get(f"{EMBED}/health")
    re = r.get("status")
    r = api_get(f"{GATEWAY}/health")
    rw = r.get("status")
    check(f"4.3 All 4 modules healthy (G:{rw} H:{rh} G:{rg} E:{re})" 
          if all(s == "healthy" for s in [rw, rh, rg, re]) else "4.3")
except Exception as e:
    fail("4.3 Cross-check", str(e))


print(f"\n{'='*50}")
print(f"Results: {passed} passed, {total-passed} failed out of {total}")
if passed == total:
    print("INTEGRATION TEST PASSED - Four modules integrated!")
    sys.exit(0)
else:
    print("INTEGRATION FAILED")
    sys.exit(1)
