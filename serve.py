import argparse
import logging
import sys
from pathlib import Path

from flask import Flask, send_from_directory, request, redirect, url_for, Response
from flask_socketio import SocketIO, emit


try:
    import coloredlogs

    _LOG_FMT = "%(asctime)s %(name)-10s %(levelname)-6s %(message)s"
    coloredlogs.install(level="INFO", fmt=_LOG_FMT)
except Exception:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-10s %(levelname)-6s %(message)s")


parser = argparse.ArgumentParser(description="Serve the script's directory over HTTP with colored logs and a Socket.IO endpoint")
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


# Create Flask app to serve static files from the script directory
app = Flask(__name__, static_folder=str(directory_path), static_url_path="")

# Configure Socket.IO. We allow CORS from anywhere for local development.
socketio = SocketIO(app, cors_allowed_origins="*")


@app.route("/")
def index():
    for fname in ("index.html", ):
        fpath = directory_path / fname
        if fpath.exists():
            return send_from_directory(str(directory_path), fname)
    # Otherwise list available html files as a simple index
    items = [p.name for p in directory_path.iterdir() if p.suffix == ".html"]
    body = "<h1>Available pages</h1>\n<ul>\n"
    for it in sorted(items):
        body += f"<li><a href=\"/{it}\">{it}</a></li>\n"
    body += "</ul>"
    return Response(body, mimetype="text/html")


@app.route('/<path:filename>')
def serve_file(filename):
    # Let Flask serve any file from the directory
    return send_from_directory(str(directory_path), filename)


@socketio.on('connect')
def on_connect():
    sid = request.sid if hasattr(request, 'sid') else None
    logger.info('Socket Client connected: %s', sid)
    emit('server_message', {'message': 'connected'})


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid if hasattr(request, 'sid') else None
    logger.info('Socket Client disconnected: %s', sid)


@socketio.on('echo')
def on_echo(data):
    # Echo back whatever the client sends on 'echo'
    logger.debug('Echo event received: %r', data)
    emit('echo', data)


def run():
    host = args.bind
    port = int(args.port)
    logger.info('Serving %s on http://%s:%s', directory_path, host, port)
    logger.info('Press Ctrl-C to stop')
    try:
        # Use eventlet/gevent if installed; flask-socketio will pick the best available.
        socketio.run(app, host=host, port=port, debug=args.debug)
    except KeyboardInterrupt:
        logger.info('Shutting down server')
        sys.exit(0)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception('Server error: %s', exc)
        sys.exit(4)


if __name__ == '__main__':
    run()
