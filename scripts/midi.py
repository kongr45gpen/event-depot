"""
midi.js
Opinionated controls of a Behringer X-AIR18 using a Behringer X-TOUCH Mini in MC mode.

MIDI protocol:

Top encoders:

control_change channel=0 control=16 value=1 time=0
control_change channel=0 control=23 value=1 time=0
value = 65 slow down
value = 71 fast down
value =  1 slow up
value =  7 fast up

Top encoder push:

note_on channel=0 note=32 velocity=127 time=0
note_on channel=0 note=32 velocity=0 time=0
note_on channel=0 note=39 velocity=127 time=0
note_on channel=0 note=39 velocity=0 time=0

Buttons:
note_on channel=0 note=89 velocity=127 time=0
note_on channel=0 note=95 velocity=127 time=0

Layers:
note_on channel=0 note=84 velocity=127 time=0
note_on channel=0 note=85 velocity=0 time=0

Main wheel:
pitchwheel channel=8 pitch=-8192 time=0
pitchwheel channel=8 pitch=4096 time=0 (75%)
pitchwheel channel=8 pitch=8064 time=0
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import mido
import confuse
import coloredlogs
import pyxair

DEFAULT_CONFIG = Path(__file__).parent / "midi.yaml"

def make_stream():
    loop = asyncio.get_event_loop()
    queue = asyncio.Queue()

    def callback(message):
        loop.call_soon_threadsafe(queue.put_nowait, message)

    async def stream():
        while True:
            yield await queue.get()

    return callback, stream()

async def monitor_midi(input_name: str, output=None):
    logger = logging.getLogger("midi")
    cb, stream = make_stream()

    try:
        logger.info("Opening input '%s'", input_name)
        mido.open_input(input_name, callback=cb)
    except (IOError, OSError) as exc:
        logger.error("Failed to open MIDI input '%s': %s", input_name, exc)
        raise

    if output is not None:
        logger.info("Output device available: %s", getattr(output, 'name', str(output)))

    async for message in stream:
        logger.debug("MIDI IN: %s", message)

async def my_amazing_loop_that_prints_something_every_second():
    logger = logging.getLogger("midi")
    while True:
        logger.info("Hello from the amazing loop!")
        await asyncio.sleep(1)


def load_config(path: Path):
    cfg = confuse.Configuration('event-depot', __name__)
    if path and path.exists():
        cfg.set_file(str(path))
    return cfg


async def main(argv=None):
    parser = argparse.ArgumentParser(description="MIDI monitor using mido + confuse config + coloredlogs")
    parser.add_argument('--config', '-c', type=Path, default=DEFAULT_CONFIG,
                        help=f"Path to YAML config (default: {DEFAULT_CONFIG})")
    parser.add_argument('--input-name', '-i', help="Override MIDI input device name from config")
    parser.add_argument('--output-name', '-o', help="Override MIDI output device name from config")
    parser.add_argument('--list', action='store_true', help="List available MIDI devices and exit")
    parser.add_argument('-v', '--verbose', action='count', default=0, help="Increase verbosity (repeatable)")
    args = parser.parse_args(argv)

    level = logging.WARNING
    if args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO

    coloredlogs.install(level=level, fmt='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
    logger = logging.getLogger('midi')

    if args.list:
        logger.info("Listing MIDI devices")
        print("Inputs:")
        for n in mido.get_input_names():
            print("  ", n)
        print("Outputs:")
        for n in mido.get_output_names():
            print("  ", n)
        return 0

    cfg = load_config(args.config)

    input_name = args.input_name or cfg['midi']['input'].get()
    output_name = args.output_name or cfg['midi']['output'].get()

    try:
        logger.info("Opening output '%s'", output_name)
        out = mido.open_output(output_name)
    except (IOError, OSError) as exc:
        logger.exception("Failed to open MIDI output '%s'", output_name)
        out = None

    try:

        xair = pyxair.XAir(pyxair.XInfo("10.20.0.216", 10024, "IRREL", "IRREL", "IRREL"))
        pubsub_task = asyncio.create_task(xair.start())
        status = await xair.get("/status")
        print(status)

        await asyncio.gather(
            monitor_midi(input_name, output=out),
            my_amazing_loop_that_prints_something_every_second()
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception:
        logger.exception("Unhandled error")
        return 4

    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))