"""E2E verification script entrypoint."""

from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE_URL = os.environ.get("ANT_COLONY_BASE_URL", "http://127.0.0.1")
GATEWAY = os.environ.get("ANT_COLONY_GATEWAY_URL", f"{BASE_URL}:18090")
GBRAIN = os.environ.get("ANT_COLONY_GBRAIN_URL", f"{BASE_URL}:8787")
HINDSIGHT = os.environ.get("ANT_COLONY_HINDSIGHT_URL", f"{BASE_URL}:8890")
EMBED = os.environ.get("ANT_COLONY_EMBED_URL", f"{BASE_URL}:8766")


class E2ERunner:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def check(self, name: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.passed += 1
            print(f"  OK {name}")
            return
        self.failed += 1
        print(f"  FAIL {name} - {detail}")

    @staticmethod
    def api_get(url: str) -> dict:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read())

    @staticmethod
    def api_post(url: str, data: dict) -> dict:
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read())

    @staticmethod
    def api_post_raw(url: str, data: dict) -> int:
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=5).getcode()

    def run(self) -> int:
        self._check_gateway()
        self._check_gbrain()
        self._check_hindsight()
        self._check_embedding()

        print(f"\n{'=' * 40}")
        print(f"Results: {self.passed} passed, {self.failed} failed out of {self.passed + self.failed}")
        if self.failed:
            print("SOME TESTS FAILED")
            return 1
        print("ALL TESTS PASSED")
        return 0

    def _check_gateway(self) -> None:
        print("\n=== L1: Gateway (:18090) ===")
        try:
            result = self.api_get(f"{GATEWAY}/health")
            self.check("Gateway health", result.get("status") == "healthy", str(result))
        except Exception as exc:
            self.check("Gateway health", False, str(exc))

        try:
            code = self.api_post_raw(GATEWAY, {"from": "e2e-test", "content": "E2E test message", "space_id": "e2e-proj"})
            self.check("Message ingest", code == 200, f"HTTP {code}")
        except Exception as exc:
            self.check("Message ingest", False, str(exc))

        try:
            result = self.api_get(f"{GATEWAY}/tasks?space_id=e2e-proj")
            self.check("Task list", "tasks" in result, f"{len(result.get('tasks', []))} tasks")
        except Exception as exc:
            self.check("Task list", False, str(exc))

    def _check_gbrain(self) -> None:
        print("\n=== L2: gbrain Cold Layer (:8787) ===")
        try:
            result = self.api_get(f"{GBRAIN}/health")
            self.check("gbrain health", result.get("status") == "healthy", str(result))
        except Exception as exc:
            self.check("gbrain health", False, str(exc))

        try:
            result = self.api_post(
                f"{GBRAIN}/mcp",
                {
                    "method": "put_page",
                    "params": {"id": "e2e-page", "title": "E2E Test", "content": "Test content for verification", "tags": ["e2e"]},
                    "id": 1,
                },
            )
            self.check("gbrain put_page", result.get("result", {}).get("status") == "ok", str(result))
        except Exception as exc:
            self.check("gbrain put_page", False, str(exc))

        try:
            result = self.api_post(f"{GBRAIN}/mcp", {"method": "get_page", "params": {"id": "e2e-page"}, "id": 2})
            self.check("gbrain get_page", result.get("result") is not None, str(result)[:100])
        except Exception as exc:
            self.check("gbrain get_page", False, str(exc))

    def _check_hindsight(self) -> None:
        print("\n=== L3: Hindsight Warm Layer (:8890) ===")
        try:
            result = self.api_get(f"{HINDSIGHT}/health")
            self.check("Hindsight health", result.get("status") == "healthy", str(result))
        except Exception as exc:
            self.check("Hindsight health", False, str(exc))

        try:
            result = self.api_post(
                f"{HINDSIGHT}/v1/default/banks/hermes/memories",
                {"id": "e2e-mem-1", "memory": "E2E verification memory entry with keywords", "tags": ["e2e", "test"]},
            )
            self.check("Hindsight retain", result.get("status") == "retained", str(result))
        except Exception as exc:
            self.check("Hindsight retain", False, str(exc))

        try:
            result = self.api_get(f"{HINDSIGHT}/v1/default/banks/hermes/memories/recall?query=verification&limit=5")
            self.check("Hindsight recall", result.get("count", 0) >= 1, f"found {result.get('count', 0)}")
        except Exception as exc:
            self.check("Hindsight recall", False, str(exc))

        try:
            result = self.api_get(f"{HINDSIGHT}/v1/default/banks/hermes/stats")
            self.check("Hindsight stats", "total_memories" in result, str(result))
        except Exception as exc:
            self.check("Hindsight stats", False, str(exc))

    def _check_embedding(self) -> None:
        print("\n=== L4: Embedding (:8766) ===")
        try:
            result = self.api_get(f"{EMBED}/health")
            self.check("Embed health", result.get("status") == "healthy", str(result))
        except Exception as exc:
            self.check("Embed health", False, str(exc))

        try:
            payload = json.dumps({"texts": ["test"]}).encode()
            req = urllib.request.Request(EMBED, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read())
            self.check("Embed encode", len(result.get("embeddings", [])) == 1, f"dim={result.get('dim')}")
        except Exception as exc:
            self.check("Embed encode", False, str(exc))


def main() -> int:
    return E2ERunner().run()


if __name__ == "__main__":
    sys.exit(main())
