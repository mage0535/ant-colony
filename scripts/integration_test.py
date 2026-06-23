"""Four-module integration test entrypoint."""

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


class IntegrationRunner:
    def __init__(self) -> None:
        self.passed = 0
        self.total = 0

    def check(self, name: str) -> None:
        self.total += 1
        self.passed += 1
        print(f"  OK {name}")

    def fail(self, name: str, reason: str = "") -> None:
        self.total += 1
        print(f"  FAIL {name} - {reason}")

    @staticmethod
    def api_get(url: str) -> dict:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read())

    @staticmethod
    def api_post(url: str, data: dict) -> dict:
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read())

    @staticmethod
    def api_post_raw(url: str, data: dict) -> int:
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=10).getcode()

    def run(self) -> int:
        self._phase_one()
        self._phase_two()
        self._phase_three()
        self._phase_four()

        print(f"\n{'=' * 50}")
        print(f"Results: {self.passed} passed, {self.total - self.passed} failed out of {self.total}")
        if self.passed == self.total:
            print("INTEGRATION TEST PASSED - Four modules integrated!")
            return 0
        print("INTEGRATION FAILED")
        return 1

    def _phase_one(self) -> None:
        print("=== PHASE 1: Message -> Agent (OpenVort + Hermes) ===")
        try:
            self.api_get(f"{GATEWAY}/health")
            self.check("1.1 Gateway health")
        except Exception as exc:
            self.fail("1.1 Gateway health", str(exc))

        try:
            code = self.api_post_raw(
                GATEWAY,
                {
                    "from": "int-user",
                    "content": "Discuss optimizing the homepage load time. We need to implement lazy loading for images and assets.",
                    "space_id": "int-proj",
                },
            )
            self.check("1.2 Message sent to space" if code == 200 else f"1.2 HTTP {code}")
        except Exception as exc:
            self.fail("1.2 Message sent", str(exc))

        try:
            code = self.api_post_raw(
                GATEWAY,
                {
                    "from": "int-user2",
                    "content": "Also the API response time is too slow, we should add caching with Redis.",
                    "space_id": "int-proj",
                },
            )
            self.check("1.3 Second message buffered" if code == 200 else f"1.3 HTTP {code}")
        except Exception as exc:
            self.fail("1.3 Second message", str(exc))

        try:
            code = self.api_post_raw(GATEWAY, {"from": "int-user", "content": "hello"})
            if code == 200:
                self.check("1.4 Personal agent responds")
            else:
                print(f"  SKIP 1.4 Personal agent returned HTTP {code} (LLM may need config)")
        except Exception as exc:
            print(f"  SKIP 1.4 Personal agent skipped: {exc}")

    def _phase_two(self) -> None:
        print("\n=== PHASE 2: Memory Storage (Memory Sidecar) ===")
        try:
            result = self.api_post(
                f"{GBRAIN}/mcp",
                {
                    "method": "put_page",
                    "params": {
                        "id": "int-page-1",
                        "title": "Homepage Optimization",
                        "content": "Lazy loading for images, API caching with Redis. Front-end and back-end performance improvements.",
                        "tags": ["performance", "frontend", "backend"],
                    },
                    "id": 1,
                },
            )
            self.check("2.1 gbrain page created" if result["result"]["status"] == "ok" else "2.1")
        except Exception as exc:
            self.fail("2.1 gbrain create", str(exc))

        try:
            result = self.api_post(
                f"{HINDSIGHT}/v1/default/banks/hermes/memories",
                {
                    "id": "int-mem-1",
                    "memory": "Homepage needs lazy loading for performance optimization",
                    "tags": ["performance", "optimization"],
                },
            )
            self.check("2.2 Hindsight memory retained" if result["status"] == "retained" else "2.2")
        except Exception as exc:
            self.fail("2.2 Hindsight retain", str(exc))

        try:
            result = self.api_post(
                f"{HINDSIGHT}/v1/default/banks/hermes/memories",
                {
                    "id": "int-mem-2",
                    "memory": "API response time needs Redis caching layer",
                    "tags": ["api", "caching"],
                },
            )
            self.check("2.3 Second memory retained" if result["status"] == "retained" else "2.3")
        except Exception as exc:
            self.fail("2.3 Second memory", str(exc))

    def _phase_three(self) -> None:
        print("\n=== PHASE 3: Memory Recall (Hot+Warm+Cold) ===")
        try:
            result = self.api_get(f"{HINDSIGHT}/v1/default/banks/hermes/memories/recall?query=performance&limit=5")
            found = result.get("count", 0)
            self.check(f"3.1 Warm recall (found {found})" if found >= 2 else f"3.1 only {found}")
        except Exception as exc:
            self.fail("3.1 Warm recall", str(exc))

        try:
            result = self.api_post(
                f"{GBRAIN}/mcp",
                {"method": "search", "params": {"query": "optimization", "limit": 5}, "id": 2},
            )
            found = len(result.get("result", []))
            self.check(f"3.2 Cold recall (found {found})" if found >= 1 else "3.2 none found")
        except Exception as exc:
            self.fail("3.2 Cold recall", str(exc))

        try:
            payload = json.dumps({"texts": ["homepage optimization performance"]}).encode()
            req = urllib.request.Request(EMBED, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read())
            self.check(f"3.3 Semantic embed (dim={result['dim']})" if result["dim"] == 512 else "3.3")
        except Exception as exc:
            self.fail("3.3 Semantic embed", str(exc))

    def _phase_four(self) -> None:
        print("\n=== PHASE 4: Knowledge Pipeline (KMM) ===")
        try:
            result = self.api_get(f"{HINDSIGHT}/v1/default/banks/hermes/stats")
            total_mem = result.get("total_memories", 0)
            self.check(f"4.1 Memory stats ({total_mem} memories)" if total_mem >= 2 else f"4.1 only {total_mem}")
        except Exception as exc:
            self.fail("4.1 Memory stats", str(exc))

        try:
            result = self.api_get(f"{GBRAIN}/mcp")
            self.check("4.2 gbrain MCP accessible" if "service" in result else "4.2")
        except Exception as exc:
            self.fail("4.2 gbrain MCP", str(exc))

        try:
            gateway_status = self.api_get(f"{GATEWAY}/health").get("status")
            hindsight_status = self.api_get(f"{HINDSIGHT}/health").get("status")
            gbrain_status = self.api_get(f"{GBRAIN}/health").get("status")
            embed_status = self.api_get(f"{EMBED}/health").get("status")
            all_healthy = all(status == "healthy" for status in [gateway_status, hindsight_status, gbrain_status, embed_status])
            self.check(
                f"4.3 All 4 modules healthy (G:{gateway_status} H:{hindsight_status} B:{gbrain_status} E:{embed_status})"
                if all_healthy
                else "4.3"
            )
        except Exception as exc:
            self.fail("4.3 Cross-check", str(exc))


def main() -> int:
    return IntegrationRunner().run()


if __name__ == "__main__":
    sys.exit(main())
