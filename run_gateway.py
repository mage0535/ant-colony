import logging
import sys

from src.gateway.webhook_server import serve


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    serve("0.0.0.0", 18090, "server-deepseek")


if __name__ == "__main__":
    main()
