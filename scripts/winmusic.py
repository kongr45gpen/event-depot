
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
                        default=7373,
                        help="Bind port for HTTP server (default: 7373)")

    parser.add_argument("-l", "--lev", dest="lev", type=float,
                        default=3.0,
                        help="Levenshtein threshold (0-1), default 3")

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
                for key in ('purl', 'purl:uri', 'website', 'txxx:purl', 'txxx:website'):
                    if key in items and items[key]:
                        meta['purl'] = str(items[key][0]) if isinstance(items[key], (list, tuple)) else str(items[key])
                        break

                for key in ('license', 'licenseurl', 'copyright', 'txxx:license', 'txxx:licenseurl'):
                    if key in items and items[key]:
                        meta['license'] = str(items[key][0]) if isinstance(items[key], (list, tuple)) else str(items[key])
                        break

            except Exception:
                _LOG.debug('Mutagen failed to read tags for %s', p, exc_info=False)

        db[str(p)] = meta

    _LOG.info('Indexed %d files under %s', len(db), music_dir)
    
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
        parts = re.split(r'\s*[-|]\s*', title)
        if len(parts) < 2:
            continue

        # Linear search all songs for match
        for song_path, meta in music_db.items():
            required = [ meta.get('author')[:10].lower(), meta.get('title')[:10].lower() ]

            # Match between parts and candidates
            success_required = 0
            # for part in parts:
                # part_clean = part.strip().lower()[:10]
                # for candidate in required:
                    # combinations_tested += 1
            for metadatum in required:
                    for part in parts:
                        part_clean = part.strip().lower()[:10]
                        combinations_tested += 1
                        if nltk.edit_distance(part_clean, metadatum) <= threshold:
                            success_required += 1
                            break
            if success_required == len(required):
                _LOG.debug(f"Edit distance between '{part_clean}' and '{metadatum}' is within threshold {threshold}")
                _LOG.debug(f"Total combinations tested so far: {combinations_tested}. Time elapsed: {1000.0 * (time.time() - start_time):.0f} ms")
                _LOG.info(f"Match found! Window title: {title} - Song: {meta.get('author')} - {meta.get('title')}")
                return meta

    _LOG.info(f"No match found :( Total combinations tested: {combinations_tested} in {1000.0 * (time.time() - start_time):.0f} ms")

    return None


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv)
    setup_logging(ns.debug, ns.quiet)

    _LOG.info("Starting winmusic with: music_dir=%s interval=%s host=%s port=%s lev=%s",
              ns.music_dir, ns.interval, ns.host, ns.port, ns.lev)

    if not ns.music_dir.exists():
        _LOG.error("Music directory does not exist: %s", ns.music_dir)
        return 2
    if not ns.music_dir.is_dir():
        _LOG.error("Music directory is not a directory: %s", ns.music_dir)
        return 2
    
    _LOG.info("Indexing music files in %s...", ns.music_dir)
    music_db = create_music_database(ns.music_dir)

    identification = identify(music_db, ns.lev)
    if identification:
        _LOG.debug(f"Identified song: {identification}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

