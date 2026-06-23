import json, logging, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from sentence_transformers import SentenceTransformer
HOST = os.environ.get("BIND_HOST", "0.0.0.0")
PORT = int(os.environ.get("BIND_PORT", "8766"))
MODEL_ID = "intfloat/multilingual-e5-small"
DIM = 384
_model = None
def get_model():
    global _model
    if _model is None:
        logging.info(f"Loading {MODEL_ID}...")
        _model = SentenceTransformer(MODEL_ID)
        logging.info("Model ready")
    return _model
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            l = int(self.headers.get("Content-Length", 0))
            b = json.loads(self.rfile.read(l))
            t = b.get("texts", [b.get("text", "")])
            if isinstance(t, str): t = [t]
            v = get_model().encode(t, normalize_embeddings=True).tolist()
            self._r(200, {"embeddings": v, "dim": DIM})
        except Exception as e:
            self._r(500, {"error": str(e)})
    def do_GET(self):
        if self.path == "/health":
            self._r(200, {"status": "healthy", "model": MODEL_ID, "dim": DIM})
    def _r(self, c, d):
        b = json.dumps(d, default=str).encode()
        self.send_response(c)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def log_message(self, f, *a):
        pass
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    s = HTTPServer((HOST, PORT), H)
    logging.info(f"Embed on {HOST}:{PORT}")
    s.serve_forever()
