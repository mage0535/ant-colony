#!/usr/bin/env python3
"""Ant Colony acceptance test entrypoint."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BASE_URL = os.environ.get("ANT_COLONY_BASE_URL", "http://127.0.0.1")
GATEWAY = os.environ.get("ANT_COLONY_GATEWAY_URL", f"{BASE_URL}:18090")
DASHBOARD = os.environ.get("ANT_COLONY_DASHBOARD_URL", f"{BASE_URL}:18092/api/v1")
GBRAIN = os.environ.get("ANT_COLONY_GBRAIN_URL", f"{BASE_URL}:8787")
HINDSIGHT = os.environ.get("ANT_COLONY_HINDSIGHT_URL", f"{BASE_URL}:8890")
EMBED = os.environ.get("ANT_COLONY_EMBED_URL", f"{BASE_URL}:8766")


class AcceptanceRunner:
    def __init__(self) -> None:
        self.ok_count = 0
        self.fail_count = 0

    def check(self, name: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.ok_count += 1
            print(f"  [PASS] {name}")
            return
        self.fail_count += 1
        print(f"  [FAIL] {name} {detail}")

    @staticmethod
    def get(url: str) -> dict:
        response = urllib.request.urlopen(url, timeout=5)
        return json.loads(response.read())

    @staticmethod
    def post(url: str, data: dict) -> dict:
        payload = json.dumps(data).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=10).read())

    @staticmethod
    def put(url: str, data: dict) -> dict:
        payload = json.dumps(data).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        response = urllib.request.urlopen(req, timeout=10)
        return json.loads(response.read())

    def run(self) -> int:
        print("ANT COLONY ACCEPTANCE TEST")
        print("=" * 50)

        self._check_services()
        self._check_chat_flow()
        self._check_tasks()
        self._check_knowledge()
        self._check_memory()
        self._check_analytics()
        self._check_utilities()

        print(f"\n{'=' * 50}")
        print(f"Passed: {self.ok_count}  Failed: {self.fail_count}")
        if self.fail_count == 0:
            print("ALL ACCEPTANCE TESTS PASSED")
            return 0
        print(f"FAILED: {self.fail_count} test(s)")
        return 1

    def _check_services(self) -> None:
        print("\n-- 1. Services --")
        for label, url, key in [
            ("Gateway", f"{GATEWAY}/health", "status"),
            ("gbrain", f"{GBRAIN}/health", "status"),
            ("Hindsight", f"{HINDSIGHT}/health", "status"),
            ("Embedding", f"{EMBED}/health", "dim"),
        ]:
            try:
                result = self.get(url)
                self.check(f"1.{label} {url}", result.get("status") == "healthy", str(result.get(key, "")))
            except Exception as exc:
                self.check(f"1.{label}", False, str(exc)[:80])

        try:
            result = self.get(f"{DASHBOARD}/health")
            self.check("1.Dashboard", result.get("status") == "healthy", str(result)[:80])
        except Exception as exc:
            self.check("1.Dashboard", False, str(exc)[:80])

    def _check_chat_flow(self) -> None:
        print("\n-- 2. Chat Flow --")
        try:
            first = urllib.request.urlopen(
                urllib.request.Request(
                    GATEWAY,
                    data=json.dumps(
                        {"from": "u1", "content": "首页加载优化到2秒", "space_id": "apt"}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                ),
                timeout=5,
            ).getcode()
            second = urllib.request.urlopen(
                urllib.request.Request(
                    GATEWAY,
                    data=json.dumps(
                        {"from": "u2", "content": "需要图片懒加载和CDN", "space_id": "apt"}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                ),
                timeout=5,
            ).getcode()
            self.check("2.1 Messages sent", first == 200 and second == 200, f"{first}/{second}")
        except Exception as exc:
            self.check("2.1 Messages", False, str(exc)[:80])

        time.sleep(35)
        try:
            result = self.get(f"{GATEWAY}/drafts?space_id=apt")
            drafts = result.get("drafts", [])
            self.check("2.2 Drafts auto-generated", len(drafts) > 0, f"got {len(drafts)}")
        except Exception as exc:
            self.check("2.2 Drafts", False, str(exc)[:80])

    def _check_tasks(self) -> None:
        print("\n-- 3. Tasks --")
        task_id = None
        try:
            result = self.post(
                f"{DASHBOARD}/tasks",
                {"title": "Acceptance Test Task", "description": "Full E2E", "project_id": "apt", "priority": "high"},
            )
            task_id = result.get("task_id")
            self.check("3.1 Create", task_id is not None, str(task_id or ""))
        except Exception as exc:
            self.check("3.1 Create", False, str(exc)[:80])

        if not task_id:
            return

        try:
            self.put(f"{DASHBOARD}/transition", {"task_id": task_id, "status": "in_progress"})
            self.put(f"{DASHBOARD}/transition", {"task_id": task_id, "status": "done"})
            result = self.get(f"{DASHBOARD}/tasks?space_id=apt")
            task = next((item for item in result["tasks"] if item["id"] == task_id), {})
            self.check("3.2 Transition", task.get("status") == "done", str(task.get("status", "")))
        except Exception as exc:
            self.check("3.2 Transition", False, str(exc)[:80])

        try:
            dependent = self.post(f"{DASHBOARD}/tasks", {"title": "Dependent Task", "project_id": "apt"})
            dependent_id = dependent.get("task_id")
            self.put(f"{DASHBOARD}/dependency", {"task_id": dependent_id, "blocked_by_task_id": task_id})
            result = self.get(f"{DASHBOARD}/tasks?space_id=apt")
            task = next((item for item in result["tasks"] if item["id"] == dependent_id), {})
            self.check("3.3 Dependency", task.get("blocked_by_task_id") == task_id, "")
        except Exception as exc:
            self.check("3.3 Dependency", False, str(exc)[:80])

        try:
            self.put(f"{DASHBOARD}/priority", {"task_id": task_id, "priority": "high"})
            self.put(f"{DASHBOARD}/deadline", {"task_id": task_id, "due_at": "2026-12-31T23:59:59"})
            result = self.get(f"{DASHBOARD}/tasks?space_id=apt")
            task = next((item for item in result["tasks"] if item["id"] == task_id), {})
            self.check("3.4 Meta", task.get("priority") == "high", str(task.get("priority")))
        except Exception as exc:
            self.check("3.4 Meta", False, str(exc)[:80])

    def _check_knowledge(self) -> None:
        print("\n-- 4. Knowledge --")
        try:
            self.post(
                f"{DASHBOARD}/knowledge",
                {"id": "ak1", "owner_type": "project", "owner_id": "apt", "content": "CDN best practices guide", "tags": ["cdn"]},
            )
            self.post(
                f"{DASHBOARD}/knowledge",
                {"id": "ak2", "owner_type": "personal", "owner_id": "u1", "content": "Frontend checklist", "tags": ["fe"]},
            )
            result = self.get(f"{DASHBOARD}/knowledge/search?query=CDN&user_id=u1&space_id=apt")
            self.check("4.1 Search", len(result.get("results", [])) >= 1, f"found {len(result.get('results', []))}")
        except Exception as exc:
            self.check("4.1 Search", False, str(exc)[:80])

        try:
            result = self.post(
                f"{DASHBOARD}/knowledge/collect",
                {"text": "Performance improved from 5s to 1.8s", "title": "Report", "owner_type": "project", "owner_id": "apt"},
            )
            self.check("4.2 Collect", result.get("id") is not None, str(result)[:60])
        except Exception as exc:
            self.check("4.2 Collect", False, str(exc)[:80])

    def _check_memory(self) -> None:
        print("\n-- 5. Memory --")
        try:
            self.post(
                f"{HINDSIGHT}/v1/default/banks/hermes/memories",
                {"id": "am1", "memory": "Lazy loading cut LCP by 60 percent", "tags": ["perf"]},
            )
            self.post(
                f"{HINDSIGHT}/v1/default/banks/hermes/memories",
                {"id": "am2", "memory": "Redis reduced API latency from 800ms", "tags": ["cache"]},
            )
            result = self.get(f"{HINDSIGHT}/v1/default/banks/hermes/memories/recall?query=latency&limit=5")
            self.check("5.1 Warm", result.get("count", 0) >= 1, f"found {result.get('count', 0)}")
        except Exception as exc:
            self.check("5.1 Warm", False, str(exc)[:80])

        try:
            self.post(
                f"{GBRAIN}/mcp",
                {"method": "put_page", "params": {"id": "ag1", "title": "Perf Guide", "content": "Web optimization", "tags": ["perf"]}, "id": 1},
            )
            result = self.post(f"{GBRAIN}/mcp", {"method": "get_page", "params": {"id": "ag1"}, "id": 2})
            self.check("5.2 Cold", result.get("result") is not None, "")
        except Exception as exc:
            self.check("5.2 Cold", False, str(exc)[:80])

        try:
            payload = json.dumps({"texts": ["performance optimization"]}).encode()
            req = urllib.request.Request(EMBED, data=payload, headers={"Content-Type": "application/json"})
            result = json.loads(urllib.request.urlopen(req, timeout=30).read())
            self.check("5.3 Embed", result["dim"] == 512, f"dim={result['dim']}")
        except Exception as exc:
            self.check("5.3 Embed", False, str(exc)[:80])

    def _check_analytics(self) -> None:
        print("\n-- 6. Analytics --")
        try:
            result = self.get(f"{DASHBOARD}/analytics")
            self.check("6.1 Stats", result.get("stats", {}).get("total", 0) > 0, f"total={result.get('stats', {}).get('total', 0)}")
        except Exception as exc:
            self.check("6.1 Stats", False, str(exc)[:80])

        try:
            result = self.get(f"{DASHBOARD}/roles?space_id=apt")
            self.check("6.2 Roles", "roles" in result, "")
        except Exception:
            self.check("6.2 Roles", False)

        try:
            result = self.get(f"{DASHBOARD}/agents")
            self.check("6.3 Agents", result.get("stats", {}).get("total_agents", 0) >= 0, "")
        except Exception:
            self.check("6.3 Agents", False)

        try:
            self.post(f"{DASHBOARD}/spaces", {"space_id": "apt", "name": "Acceptance Test Space", "space_type": "project"})
            result = self.get(f"{DASHBOARD}/spaces")
            self.check("6.4 Spaces", result.get("total_spaces", 0) > 0, "")
        except Exception:
            self.check("6.4 Spaces", False)

    def _check_utilities(self) -> None:
        print("\n-- 7. Utilities --")
        try:
            result = self.get(f"{DASHBOARD}/reminders?space_id=apt")
            self.check("7.1 Reminders", "reminders" in result, "")
        except Exception:
            self.check("7.1 Reminders", False)

        try:
            result = self.get(f"{DASHBOARD}/tasks/export?format=json&space_id=apt")
            self.check("7.2 Export", result.get("count", 0) > 0, f"count={result.get('count', 0)}")
        except Exception:
            self.check("7.2 Export", False)

        try:
            result = self.get(f"{DASHBOARD}/files?space_id=apt")
            self.check("7.3 Files", "files" in result, "")
        except Exception:
            self.check("7.3 Files", False)

        try:
            result = self.get(f"{DASHBOARD}/journal/u1")
            self.check("7.4 Journal", "total_tasks" in result, "")
        except Exception:
            self.check("7.4 Journal", False)


def main() -> int:
    return AcceptanceRunner().run()


if __name__ == "__main__":
    sys.exit(main())
