import logging
import sys
import uvicorn

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s [%(levelname)s] %(message)s")

if __name__ == "__main__":
    uvicorn.run("src.web.dashboard:app", host="0.0.0.0", port=18092, log_level="info")
