import argparse
import logging
import sys
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from http.server import HTTPServer
from functools import partial
from pathlib import Path


# Install coloredlogs if available; otherwise, configure basic logging.
try:
    import coloredlogs

    _LOG_FMT = "%(asctime)s %(levelname)s %(message)s"
    coloredlogs.install(level="INFO", fmt=_LOG_FMT)
except Exception:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


parser = argparse.ArgumentParser(description="Serve the script's directory over HTTP with colored logs")
parser.add_argument("--port", "-p", type=int, default=8080, help="Port to listen on")
parser.add_argument("--bind", "-b", default="0.0.0.0", help="Bind address")
parser.add_argument("-q", "--quiet", action="store_true", help="Reduce logging output to WARNING")
parser.add_argument("-d", "--debug", action="store_true", help="Enable DEBUG logging")

args = parser.parse_args()

if args.debug:
    level = logging.DEBUG
elif args.quiet:
    level = logging.WARNING
else:
    level = logging.INFO

logging.getLogger().setLevel(level)

logger = logging.getLogger("server")


directory_path = Path(__file__).parent.resolve()
if not directory_path.exists():
    logger.error("Script directory does not exist: %s", directory_path)
    sys.exit(2)


handler = partial(SimpleHTTPRequestHandler, directory=str(directory_path))
try:
    server = ThreadingHTTPServer((args.bind, int(args.port)), handler)
except OSError as exc:
    logger.error("Failed to start server on %s:%s — %s", args.bind, args.port, exc)
    sys.exit(3)

addr, used_port = server.server_address
logger.info("Serving %s on http://%s:%s", directory_path, addr, used_port)
logger.info("Press Ctrl-C to stop")

try:
    server.serve_forever()
except KeyboardInterrupt:
    logger.info("Shutting down server")
    server.shutdown()
    server.server_close()
    sys.exit(0)
except Exception as exc:  # pragma: no cover - defensive
    logger.exception("Server error: %s", exc)
    sys.exit(4)
