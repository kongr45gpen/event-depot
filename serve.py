import argparse
import logging
import sys
from pathlib import Path

from flask import Flask, send_from_directory, request, redirect, url_for, Response, jsonify
from flask_socketio import SocketIO, emit


try:
    import coloredlogs

    _LOG_FMT = "%(asctime)s %(name)-10s %(levelname)-6s %(message)s"
    coloredlogs.install(level="INFO", fmt=_LOG_FMT)
except Exception:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-10s %(levelname)-6s %(message)s")

class LiveData:
    def __init__(self):
        self.boxes = []
        self.big_box = None
    
    def to_dict(self):
        return {"boxes": self.boxes, "big_box": self.big_box}

    def update_from(self, data):
        if not isinstance(data, dict):
            raise TypeError("Expected data to be a dict")

        if 'boxes' in data:
            boxes = data.get('boxes')
            if not isinstance(boxes, list):
                raise TypeError("'boxes' must be a list")

            if len(boxes) > 4:
                raise ValueError("At most 4 boxes are allowed")

            new_boxes = []
            for idx, box in enumerate(boxes):
                if not isinstance(box, (list, tuple)):
                    raise TypeError(f"Box at index {idx} must be a list/tuple")
                vals = []
                for v in box:
                    try:
                        vnum = float(v)
                    except Exception:
                        raise ValueError(f"Box at index {idx} contains non-numeric value")
                    vals.append(vnum)
    
            self.boxes = new_boxes

        if 'big_box' in data:
            size = float(data.get('big_box'))

            if size > 100 or size < 0:
                raise ValueError("Your big box is unacceptable.")

            self.big_box = size

    def __str__(self):
        return f"LiveData(boxes={self.boxes}, big_box={self.big_box})"

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

# Global LiveData instance
live_data = LiveData()


@app.route('/api/set', methods=['POST'])
def api_update_livedata():
    if not request.is_json:
        return jsonify({"error": "Expected application/json"}), 400

    data = request.get_json()

    try:
        live_data.update_from(data)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception('Unexpected error while updating LiveData')
        return jsonify({"error": "Internal server error"}), 500

    logger.info('LiveData updated: %s', live_data)

    try:
        socketio.emit('livedata', live_data.to_dict())
    except Exception:
        logger.exception('Failed to emit livedata')

    return jsonify({}), 200


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


@socketio.on('get_livedata')
def on_get_livedata(_data=None):
    try:
        current = live_data.to_dict()
    except Exception:
        logger.exception('Failed to read LiveData')

    try:
        return current
    finally:
        try:
            sid = request.sid if hasattr(request, 'sid') else None
            if sid:
                emit('livedata', current, room=sid)
        except Exception:
            logger.debug('Failed to emit livedata to room')


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
