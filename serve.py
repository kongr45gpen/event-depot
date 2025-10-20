import argparse
import logging
import sys
from pathlib import Path
import json

from flask import Flask, send_from_directory, request, redirect, url_for, Response, jsonify
import re
from flask_socketio import SocketIO, emit


try:
    import coloredlogs

    _LOG_FMT = "%(asctime)s %(name)-10s %(levelname)-6s %(message)s"
    coloredlogs.install(level="INFO", fmt=_LOG_FMT)
except Exception:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-10s %(levelname)-6s %(message)s")

class LiveData:
    def __init__(self):
        self._data = {
            'boxes': [],
            'big_box': None,
            'big_box_aspect_ratio': 16/9,
            'big_box_x': None,
            'big_box_y': None,
        }
        self._persist_path = None

    def to_dict(self):
        # Return a shallow copy so callers can't mutate internal state directly
        return dict(self._data)

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
                vals = [0, 0, 1, 0, 0, 0, 0]
                for i, v in enumerate(box):
                    try:
                        vnum = float(v)
                        vals[i] = vnum
                    except Exception:
                        raise ValueError(f"Box at index {idx} contains non-numeric value")
                    if len(vals) > 7:
                        raise ValueError(f"You can't fill your boxes with too much stuff.")
                new_boxes.append(vals)

            self._data['boxes'] = new_boxes

        if 'big_box' in data:
            size = float(data.get('big_box')) if data.get('big_box') is not None else None

            if size > 100 or size < 0:
                raise ValueError("Your big box is unacceptable.")

            self._data['big_box'] = size

        if 'big_box_aspect_ratio' in data:
            r = float(data.get('big_box_aspect_ratio')) if data.get('big_box_aspect_ratio') is not None else None

            if r <= 0.001 or r > 100:
                raise ValueError("Your big box is not doing very well.")

            self._data['big_box_aspect_ratio'] = r

        if 'big_box_x' in data:
            self._data['big_box_x'] = float(data.get('big_box_x')) if data.get('big_box_x') is not None else None
        if 'big_box_y' in data:
            self._data['big_box_y'] = float(data.get('big_box_y')) if data.get('big_box_y') is not None else None

    def __str__(self):
        return f"LiveData({self.to_dict()})"

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

class LiveDataStore:
    OUTPUT_KEY_RE = re.compile(r'^[A-Za-z0-9-]{1,5}$')

    def __init__(self):
        # mapping from output key -> LiveData
        self._data = {}
        self._current = 'PRV'
        self._preview = 'PRV'
        self._persist_path = None

    def validate_key(self, key: str) -> bool:
        return isinstance(key, str) and bool(self.OUTPUT_KEY_RE.match(key))

    def get_data_at(self, key: str) -> LiveData:
        if key not in self._data:
            logging.getLogger('server').info(f'Creating new LiveData for output key: {key}')
            self._data[key] = LiveData()
        return self._data[key]

    def set_current_key(self, key: str) -> None:
        if not self.validate_key(key):
            raise ValueError('Invalid output key')
        self._current = key

    def set_preview_key(self, key: str) -> None:
        if not self.validate_key(key):
            raise ValueError('Invalid preview output key')
        self._preview = key

    def get_preview_key(self) -> str:
        return self._preview

    def swap_current_and_preview(self) -> None:
        if not isinstance(self._preview, str) or not self.validate_key(self._preview):
            raise ValueError('No valid preview to transition with')
        # ensure both outputs exist in store
        self.get_data_at(self._preview)
        self.get_data_at(self._current)
        self._current, self._preview = self._preview, self._current

    def get_current_key(self) -> str:
        return self._current

    def get_data(self) -> LiveData:
        return self.get_data_at(self._current)

    def to_persist_dict(self):
        return {
            'current': self._current,
            'preview': self._preview,
            'outputs': {k: v.to_dict() for k, v in self._data.items()}
        }

    def save(self) -> None:
        try:
            data = self.to_persist_dict()
            with self._persist_path.open('w', encoding='utf-8') as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except Exception:
            logging.getLogger('server').exception('Failed to save LiveDataStore')

    def load(self) -> None:
        try:
            if not self._persist_path.exists():
                return
            with self._persist_path.open('r', encoding='utf-8') as fh:
                data = json.load(fh)
                cur = data.get('current', 'PRV')
                outputs = data.get('outputs', {}) or {}
                for k, v in outputs.items():
                    try:
                        if not self.validate_key(k):
                            logger.warning('Skipping invalid persisted output key: %s', k)
                            continue
                        ld = LiveData()
                        ld.update_from(v or {})
                        logging.getLogger('server').debug(f'Loaded persisted LiveData for output {k}: {ld}')
                        self._data[k] = ld
                    except Exception:
                        logger.exception('Failed to load output %s', k)
                if isinstance(cur, str) and self.validate_key(cur):
                    self._current = cur
                preview_val = data.get('preview', 'PRV')
                if isinstance(preview_val, str) and self.validate_key(preview_val):
                    self._preview = preview_val
        except Exception:
            logging.getLogger('server').exception('Failed to load persisted LiveDataStore')


live_store = LiveDataStore()

# Configure persistence file and load existing data if any
try:
    persist_file = directory_path / 'livedata.json'
    live_store._persist_path = persist_file
    live_store.load()
except Exception:
    logger.exception('Failed to initialize persisted LiveDataStore')


@app.route('/api/set', methods=['POST'])
def api_update_livedata():
    if not request.is_json:
        return jsonify({"error": "Expected application/json"}), 400

    data = request.get_json()

    # determine output key from payload or use default
    output = data.get('output', 'PRV') if isinstance(data, dict) else 'PRV'
    try:
        if not live_store.validate_key(output):
            raise ValueError('Invalid output key')
        target = live_store.get_data_at(output)
        target.update_from(data)
    except (ValueError, TypeError) as exc:
        logger.warning('Invalid data for LiveData update: %s', exc)
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception('Unexpected error while updating LiveData')
        return jsonify({"error": "Internal server error"}), 500

    logger.info(f'LiveData updated for output {output}: {target}')

    try:
        socketio.emit('livedata', live_store.get_data().to_dict())
    except Exception:
        logger.exception('Failed to emit livedata')

    try:
        live_store.save()
    except Exception:
        logging.getLogger('server').warning('Failed to persist LiveDataStore')

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
        current = live_store.get_data().to_dict()
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


@app.route('/api/output', methods=['POST'])
def api_set_current():
    try:
        if not request.is_json:
            raise TypeError("Expected application/json")

        data = request.get_json()
        if not isinstance(data, dict):
            raise TypeError("Expected JSON object")

        output_key = data.get('output')
        preview_key = data.get('preview')
        transition_present = 'transition' in data

        # validate optional keys when present
        if output_key is not None and not isinstance(output_key, str):
            raise TypeError("Invalid 'output' value")
        if preview_key is not None and not isinstance(preview_key, str):
            raise TypeError("Invalid 'preview' value")

        # Handle preview/transition logic: all fields optional
        if transition_present:
            # swap current and preview
            live_store.swap_current_and_preview()
            logging.getLogger('server').info(f'Transitioned current and preview: current={live_store.get_current_key()}, preview={live_store.get_preview_key()}')
            
        if output_key is not None:
            if not live_store.validate_key(output_key):
                raise ValueError('Invalid output key')
            live_store.set_current_key(output_key)
            logging.getLogger('server').info(f'Set current output to: {output_key}')

        if preview_key is not None:
            if not live_store.validate_key(preview_key):
                raise ValueError('Invalid preview output key')
            live_store.set_preview_key(preview_key)
            logging.getLogger('server').info(f'Set preview output to: {preview_key}')

        # persist and emit new current livedata
        try:
            live_store.save()
        except Exception:
            logger.warning('Failed to persist LiveDataStore')

        current = live_store.get_data().to_dict()
        socketio.emit('livedata', current)

        return jsonify({}), 200
    except Exception as exc:
        # log exception and return JSON error (400 for validation errors)
        logger.exception('Failed to set current output: %s', exc)
        if isinstance(exc, (ValueError, TypeError)):
            return jsonify({"error": str(exc)}), 400
        return jsonify({"error": "Internal server error"}), 500


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
