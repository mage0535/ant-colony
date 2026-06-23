import logging
import sys

from src.gateway.wecom_callback_server import serve


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    serve("0.0.0.0", 18091)


if __name__ == "__main__":
    main()
