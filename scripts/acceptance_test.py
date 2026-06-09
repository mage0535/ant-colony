#!/usr/bin/env python3
"""Ant Colony Acceptance Test — simplified, reliable version."""
import json, sys, time, urllib.request


ok_count = 0
fail_count = 0

def check(name, condition, detail=""):
    global ok_count, fail_count
    if condition:
        ok_count += 1
        print(f"  [PASS] {name}")
    else:
        fail_count += 1
        print(f"  [FAIL] {name} {detail}")

def get(url):
    r = urllib.request.urlopen(url, timeout=5)
    return json.loads(r.read())

def post(url, data):
    b = json.dumps(data).encode()
    r = urllib.request.Request(url, data=b, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=10).read())

def put(url, data):
    b = json.dumps(data).encode()
    r = urllib.request.Request(url, data=b, headers={"Content-Type": "application/json"}, method="PUT")
    resp = urllib.request.urlopen(r, timeout=10)
    return json.loads(resp.read())

print("ANT COLONY ACCEPTANCE TEST")
print("=" * 50)

# ---- 1. All services reachable ----
print("\n-- 1. Services --")
for label, url, key in [
    ("Gateway", f"{G}/health", "status"),
    ("gbrain", f"{GB}/health", "status"),
    ("Hindsight", f"{HS}/health", "status"),
    ("Embedding", f"{EM}/health", "dim"),
]:
    try:
        r = get(url)
        check(f"1.{label} {url}", r.get("status") == "healthy", r.get(key, ""))
    except Exception as e:
        check(f"1.{label}", False, str(e)[:80])

try:
    r = get(f"{D}/health")
    check("1.Dashboard", r.get("status") == "healthy", str(r)[:80])
except Exception as e:
    check("1.Dashboard", False, str(e)[:80])

# ---- 2. Chat flow ----
print("\n-- 2. Chat Flow --")
try:
    code = urllib.request.urlopen(urllib.request.Request(
        G, data=json.dumps({"from":"u1","content":"首页加载优化到2秒","space_id":"apt"}).encode(),
        headers={"Content-Type":"application/json"}), timeout=5).getcode()
    code2 = urllib.request.urlopen(urllib.request.Request(
        G, data=json.dumps({"from":"u2","content":"需要图片懒加载和CDN","space_id":"apt"}).encode(),
        headers={"Content-Type":"application/json"}), timeout=5).getcode()
    check("2.1 Messages sent", code == 200 and code2 == 200, f"{code}/{code2}")
except Exception as e:
    check("2.1 Messages", False, str(e)[:80])

time.sleep(35)
try:
    r = get(f"{G}/drafts?space_id=apt")
    drafts = r.get("drafts", [])
    check(f"2.2 Drafts auto-generated", len(drafts) > 0, f"got {len(drafts)}")
except Exception as e:
    check("2.2 Drafts", False, str(e)[:80])

# ---- 3. Task operations ----
print("\n-- 3. Tasks --")
task_id = None
try:
    r = post(f"{D}/tasks", {"title":"Acceptance Test Task","description":"Full E2E","project_id":"apt","priority":"high"})
    task_id = r.get("task_id")
    check("3.1 Create", task_id is not None, task_id or "")
except Exception as e:
    check("3.1 Create", False, str(e)[:80])

if task_id:
    try:
        put(f"{D}/transition", {"task_id": task_id, "status": "in_progress"})
        put(f"{D}/transition", {"task_id": task_id, "status": "done"})
        r = get(f"{D}/tasks?space_id=apt")
        t = next((x for x in r["tasks"] if x["id"] == task_id), {})
        check("3.2 Transition", t.get("status") == "done", t.get("status", ""))
    except Exception as e:
        check("3.2 Transition", False, str(e)[:80])

    try:
        from datetime import datetime, timedelta
        r2 = post(f"{D}/tasks", {"title":"Dependent Task","project_id":"apt"})
        tid2 = r2.get("task_id")
        put(f"{D}/dependency", {"task_id": tid2, "blocked_by_task_id": task_id})
        r = get(f"{D}/tasks?space_id=apt")
        t2 = next((x for x in r["tasks"] if x["id"] == tid2), {})
        check("3.3 Dependency", t2.get("blocked_by_task_id") == task_id, "")
    except Exception as e:
        check("3.3 Dependency", False, str(e)[:80])

    try:
        put(f"{D}/priority", {"task_id": task_id, "priority": "high"})
        put(f"{D}/deadline", {"task_id": task_id, "due_at": "2026-12-31T23:59:59"})
        r = get(f"{D}/tasks?space_id=apt")
        t = next((x for x in r["tasks"] if x["id"] == task_id), {})
        check("3.4 Meta", t.get("priority") == "high", str(t.get("priority")))
    except Exception as e:
        check("3.4 Meta", False, str(e)[:80])

# ---- 4. Knowledge ----
print("\n-- 4. Knowledge --")
try:
    post(f"{D}/knowledge", {"id":"ak1","owner_type":"project","owner_id":"apt","content":"CDN best practices guide","tags":["cdn"]})
    post(f"{D}/knowledge", {"id":"ak2","owner_type":"personal","owner_id":"u1","content":"Frontend checklist","tags":["fe"]})
    r = get(f"{D}/knowledge/search?query=CDN&user_id=u1&space_id=apt")
    check("4.1 Search", len(r.get("results", [])) >= 1, f"found {len(r.get('results',[]))}")
except Exception as e:
    check("4.1 Search", False, str(e)[:80])

try:
    r = post(f"{D}/knowledge/collect", {"text":"Performance improved from 5s to 1.8s","title":"Report","owner_type":"project","owner_id":"apt"})
    check("4.2 Collect", r.get("id") is not None, str(r)[:60])
except Exception as e:
    check("4.2 Collect", False, str(e)[:80])

# ---- 5. Memory ----
print("\n-- 5. Memory --")
try:
    post(f"{HS}/v1/default/banks/hermes/memories", {"id":"am1","memory":"Lazy loading cut LCP by 60 percent","tags":["perf"]})
    post(f"{HS}/v1/default/banks/hermes/memories", {"id":"am2","memory":"Redis reduced API latency from 800ms","tags":["cache"]})
    r = get(f"{HS}/v1/default/banks/hermes/memories/recall?query=latency&limit=5")
    check("5.1 Warm", r.get("count", 0) >= 1, f"found {r.get('count',0)}")
except Exception as e:
    check("5.1 Warm", False, str(e)[:80])

try:
    post(f"{GB}/mcp", {"method":"put_page","params":{"id":"ag1","title":"Perf Guide","content":"Web optimization","tags":["perf"]},"id":1})
    r = post(f"{GB}/mcp", {"method":"get_page","params":{"id":"ag1"},"id":2})
    check("5.2 Cold", r.get("result") is not None, "")
except Exception as e:
    check("5.2 Cold", False, str(e)[:80])

try:
    d = json.dumps({"texts":["performance optimization"]}).encode()
    req = urllib.request.Request(EM, data=d, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=30)
    r = json.loads(resp.read())
    check("5.3 Embed", r["dim"] == 512, f"dim={r['dim']}")
except Exception as e:
    check("5.3 Embed", False, str(e)[:80])

# ---- 6. Analytics ----
print("\n-- 6. Analytics --")
try:
    r = get(f"{D}/analytics")
    check("6.1 Stats", r.get("stats", {}).get("total", 0) > 0, f"total={r.get('stats',{}).get('total',0)}")
except Exception as e:
    check("6.1 Stats", False, str(e)[:80])

try:
    r = get(f"{D}/roles?space_id=apt")
    check("6.2 Roles", "roles" in r, "")
except: check("6.2 Roles", False)

try:
    r = get(f"{D}/agents")
    check("6.3 Agents", r.get("stats", {}).get("total_agents", 0) >= 0, "")
except: check("6.3 Agents", False)

try:
    post(f"{D}/spaces", {"space_id":"apt","name":"Acceptance Test Space","space_type":"project"})
    r = get(f"{D}/spaces")
    check("6.4 Spaces", r.get("total_spaces", 0) > 0, "")
except: check("6.4 Spaces", False)

# ---- 7. Rest ----
print("\n-- 7. Utilities --")
try:
    r = get(f"{D}/reminders?space_id=apt")
    check("7.1 Reminders", "reminders" in r, "")
except: check("7.1 Reminders", False)

try:
    r = get(f"{D}/tasks/export?format=json&space_id=apt")
    check(f"7.2 Export", r.get("count", 0) > 0, f"count={r.get('count',0)}")
except: check("7.2 Export", False)

try:
    r = get(f"{D}/files?space_id=apt")
    check("7.3 Files", "files" in r, "")
except: check("7.3 Files", False)

try:
    r = get(f"{D}/journal/u1")
    check("7.4 Journal", "total_tasks" in r, "")
except: check("7.4 Journal", False)

# Summary
print(f"\n{'='*50}")
print(f"Passed: {ok_count}  Failed: {fail_count}")
if fail_count == 0:
    print("ALL ACCEPTANCE TESTS PASSED")
    sys.exit(0)
else:
    print(f"FAILED: {fail_count} test(s)")
    sys.exit(1)
