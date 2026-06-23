import asyncio
import logging
import sys

from src.gateway.wecom_bot_bridge import run_wecom_bot_bridge


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(run_wecom_bot_bridge())


if __name__ == "__main__":
    main()
