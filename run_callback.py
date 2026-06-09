import logging, sys
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
from src.gateway.wecom_callback_server import serve
serve("0.0.0.0", 18091)
