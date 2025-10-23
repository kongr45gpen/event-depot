
"""scripts/winmusic.py
An awesome little script that finds potential songs being played by the current application,
searches your music database for titles and artists that match, and then serves infromation about them.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
import re
import pywinctl as pwc
import nltk
import time
from flask import Flask, app, request, jsonify, make_response

# Maximum length (in characters) to compare when matching parts of titles/authors
MAX_COMPARE_LENGTH = 10

try:
    import coloredlogs
except Exception:
    coloredlogs = None

from mutagen import File as MutagenFile

_LOG = logging.getLogger("winmusic")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for winmusic.
    """
    parser = argparse.ArgumentParser(description="WinMusic helper: detect playing music and serve a small HTTP status endpoint")

    parser.add_argument("-m", "--music-dir", dest="music_dir", type=Path,
                        default=Path.cwd(),
                        help="Directory containing music files (default: .)")

    parser.add_argument("-i", "--interval", dest="interval", type=float,
                        default=5.0,
                        help="Check interval in seconds (float), default=5.0")

    parser.add_argument("-H", "--host", dest="host", type=str,
                        default="0.0.0.0",
                        help="Bind host for HTTP server (default: 0.0.0.0)")

    parser.add_argument("-p", "--port", dest="port", type=int,
                        default=7372,
                        help="Bind port for HTTP server (default: 7372)")

    parser.add_argument("-l", "--lev", dest="lev", type=float,
                        default=3.0,
                        help="Levenshtein threshold, default 3")
    
    parser.add_argument("-n", "--no-server", action="store_true",
                        help="Run identification once and exit without starting server")

    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("-q", "--quiet", action="store_true", help="Reduce logging to WARNING")

    ns = parser.parse_args(argv)

    # Basic validation
    if ns.interval <= 0:
        parser.error("--interval must be positive")

    if ns.port <= 0 or ns.port > 65535:
        parser.error("--port must be a valid TCP port (1-65535)")

    return ns


def setup_logging(debug: bool = False, quiet: bool = False) -> None:
    """Configure logging using coloredlogs when available.

    Debug flag raises level to DEBUG. Quiet sets WARNING. Default is INFO.
    """
    if debug:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.INFO

    if coloredlogs is not None:
        fmt = "%(asctime)s %(name)-12s %(levelname)-8s %(message)s"
        coloredlogs.install(level=level, fmt=fmt)
    else:
        logging.basicConfig(level=level, format="%(asctime)s %(name)-12s %(levelname)-8s %(message)s")

def create_music_database(music_dir: Path) -> None:
    """Scan `music_dir` recursively and build a simple metadata database.

    Returns a dict mapping file path (str) -> metadata dict with keys:
      - author
      - title
      - purl
      - license

    This function will try to use mutagen when available to read tags.
    If mutagen is not present or tags are missing, it will attempt to
    infer author/title from the filename ("Artist - Title.ext").
    """
    db: dict[str, dict] = {}

    for p in sorted(music_dir.rglob('*')):
        if not p.is_file():
            continue

        meta = {'author': None, 'title': None, 'purl': None, 'license': None, 'path': str(p)}

        if MutagenFile is not None:
            try:
                f = MutagenFile(str(p))
                tags = getattr(f, 'tags', None)

                if not tags:
                    continue

                # normalize tag keys to lowercase strings for lookup
                try:
                    items = {k.lower(): tags[k] for k in tags.keys()}
                except Exception:
                    # fallback for tag types that don't support keys()
                    items = {}
                    for k in tags:
                        try:
                            items[str(k).lower()] = tags[k]
                        except Exception:
                            pass

                # common artist/title keys
                for key in ('artist', 'tpe1', '©art', '©art', '©nam', 'author'):
                    if key in items and items[key]:
                        meta['author'] = str(items[key][0]) if isinstance(items[key], (list, tuple)) else str(items[key])
                        break

                for key in ('title', 'tit2', '©nam'):
                    if key in items and items[key]:
                        meta['title'] = str(items[key][0]) if isinstance(items[key], (list, tuple)) else str(items[key])
                        break

                # purl/license may be stored in TXXX frames or custom tags
                for key in ('purl', 'purl:uri', 'website', 'txxx:purl', 'txxx:website', 'woaf', 'wors', 'woas', 'wpub'):
                    if key in items and items[key]:
                        meta['purl'] = str(items[key][0]) if isinstance(items[key], (list, tuple)) else str(items[key])
                        break

                for key in ('license', 'licenseurl', 'copyright', 'txxx:license', 'txxx:licenseurl', 'tcop', 'wcop'):
                    if key in items and items[key]:
                        meta['license'] = str(items[key][0]) if isinstance(items[key], (list, tuple)) else str(items[key])
                        break

            except Exception:
                _LOG.debug(f'Mutagen failed to read tags for {p}', exc_info=False)

        db[str(p)] = meta

    _LOG.info(f'Indexed {len(db)} files under {music_dir}')
    
    # import json
    # print(json.dumps(db, indent=2))

    return db

def identify(music_db: dict[str, dict], threshold) -> dict:
    titles = pwc.getAllTitles()
    _LOG.debug(f"Current window titles: {titles}")

    # Fun statistics
    combinations_tested = 0
    start_time = time.time()

    for title in titles:
        # Try to split title based on - or |
        title = title.replace("▶︎", "").strip()
        parts = re.split(r'\s*[-|—]\s*', title)
        if len(parts) < 2:
            continue
        print(parts)

        # Linear search all songs for match
        for song_path, meta in music_db.items():
            required = [ meta.get('author').strip()[:MAX_COMPARE_LENGTH].lower().strip(), meta.get('title').strip()[:MAX_COMPARE_LENGTH].lower().strip() ]

            # Match between parts and candidates
            success_required = 0
            for metadatum in required:
                for part in parts:
                    part_clean = part.strip().lower()[:MAX_COMPARE_LENGTH].strip()
                    combinations_tested += 1
                    if nltk.edit_distance(part_clean, metadatum) <= threshold:
                        success_required += 1
                        break
            if success_required == len(required):
                _LOG.debug(f"Edit distance between '{part_clean}' and '{metadatum}' is {nltk.edit_distance(part_clean, metadatum)} < {threshold}")
                _LOG.debug(f"Total combinations tested so far: {combinations_tested}. Time elapsed: {1000.0 * (time.time() - start_time):.0f} ms")
                _LOG.info(f"Match found! Window title: [{title}] Song: [{meta.get('author')}] [{meta.get('title')}]")
                _LOG.debug(f"Matched song metadata: {meta}")
                return meta

    _LOG.info(f"No match found :( Total combinations tested: {combinations_tested} in {1000.0 * (time.time() - start_time):.0f} ms")

    return None


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv)
    setup_logging(ns.debug, ns.quiet)

    _LOG.info(f"Starting winmusic with: music_dir={ns.music_dir} interval={ns.interval} host={ns.host} port={ns.port} lev={ns.lev}")
    
    _LOG.info("NOTE: You need to restart the script if the tags/files of the directory are changed.")

    if not ns.music_dir.exists():
        _LOG.error(f"Music directory does not exist: {ns.music_dir}")
        return 2
    if not ns.music_dir.is_dir():
        _LOG.error(f"Music directory is not a directory: {ns.music_dir}")
        return 2
    
    _LOG.debug(f"Indexing music files in {ns.music_dir}...")
    music_db = create_music_database(ns.music_dir)

    if ns.no_server:
        _LOG.info("Running single identification pass (no server mode)...")
        result = identify(music_db, ns.lev)
        if result is None:
            _LOG.error("No match found.")
            return 1
        else:
            _LOG.info(f"Full result: {result}")
            print(f"Match found!")
            print(f"Author: {result.get('author')}")
            print(f"Title: {result.get('title')}")
            print(f"Path: {result.get('path')}")
            return 0

    # Create a minimal Flask app that exposes a POST /identify endpoint
    app = Flask(__name__)

    @app.route('/', defaults={'path': ''}, methods=['POST', 'OPTIONS'])
    @app.route('/<path:path>', methods=['POST', 'OPTIONS'])
    def catch_all(path: None):
        # Handle CORS preflight
        if request.method == 'OPTIONS':
            resp = make_response('', 204)
            resp.headers['Access-Control-Allow-Origin'] = '*'
            resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            return resp

        try:
            result = identify(music_db, ns.lev)
            if result is None:
                resp = jsonify({})
                resp.status_code = 404
            else:
                resp = jsonify(result)
                resp.status_code = 200
        except Exception:
            _LOG.exception('Error during identification')
            resp = jsonify({'error': 'identification_failed'})
            resp.status_code = 500

        # Allow any origin
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

    try:
        _LOG.info(f'Starting HTTP identify server on {ns.host}:{ns.port}')
        app.run(host=ns.host, port=ns.port)
    except KeyboardInterrupt:
        _LOG.info('Server stopped')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

