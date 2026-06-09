"""Ant Colony — Gateway entry point."""
import logging
import sys

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
from src.gateway.webhook_server import serve
serve("0.0.0.0", 18090, "server-deepseek")
