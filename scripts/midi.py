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

Output for Top Encoders (controls 48-55):

Single Mode (only 1 bar)
Send Control Change, channel : 1, number : 48, value 1
Send Control Change, channel : 1, number : 48, value 12

Trim (bars from center, pan style)
Send Control Change, channel : 1, number : 48, value 17
Send Control Change, channel : 1, number : 48, value 26

Fan:
Send Control Change, channel : 1, number : 48, value 33
Send Control Change, channel : 1, number : 48, value 43

Spread:
Send Control Change, channel : 1, number : 48, value 49
Send Control Change, channel : 1, number : 48, value 54
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
import contextlib

DEFAULT_CONFIG = Path(__file__).parent / "midi.yaml"

BUTTON_IXES = [
    89, 90, 40, 41, 42, 43, 44, 45,
    87, 88, 91, 92, 86, 93, 94, 95
]

LAYER_BUTTONS = [84, 85]

ENCODER_STYLES = {
    "single": (1, 11),
    "trim": (17, 9),
    "fan": (33, 10),
    "spread": (49, 5),
}

OSC_CACHE = {}

ACTIVE_KEYS = set()

CURRENT_LAYER = 0

async def create_osc_cache(configuration, xair):
    global OSC_CACHE, ACTIVE_KEYS

    keys = []

    xair._cache = {}
    
    layers = configuration['layers']
    for layer in layers:
        keys += layer['encoders'].get(confuse.Sequence(confuse.Optional(str)))
        keys += layer['buttons'].get(confuse.Sequence(confuse.Optional(str)))
    
    for key in keys:
        if key:
            ACTIVE_KEYS.add(key)
            try:
                message = await xair.get(key)
                OSC_CACHE[key] = message.arguments[0]
            except Exception as exc:
                logging.error(f"Failed to get initial OSC value for {key}: {exc}")
    
    logging.debug(f"Initialized OSC cache with: {OSC_CACHE}")

class EncoderInput:
    def __init__(self, zero_index: int, diff: float):
        self.index = zero_index
        self.diff = diff

    def __repr__(self):
        return f"EncoderInput(index={self.index}, diff={self.diff})"
    
class ButtonInput:
    def __init__(self, zero_index_row, zero_index_col):
        self.row = zero_index_row
        self.col = zero_index_col

    def __repr__(self):
        return f"ButtonInput(row={self.row}, col={self.col})"
    
class LayerSwitchInput:
    def __init__(self, layer_index):
        self.layer_index = layer_index

    def __repr__(self):
        return f"LayerSwitchInput(layer_index={self.layer_index})"

def midi_to_input(message):
    if message.type == 'control_change':
        index = message.control - 16
        diff = message.value
        if diff > 64:
            diff = - (diff - 64)
        return EncoderInput(zero_index=index, diff=diff)
    elif message.type == 'note_on':
        if message.velocity != 127:
            return None
        
        if message.note in LAYER_BUTTONS:
            layer_index = LAYER_BUTTONS.index(message.note)
            return LayerSwitchInput(layer_index=layer_index)

        if message.note in BUTTON_IXES:
            ix = BUTTON_IXES.index(message.note)
            row = ix // 8 + 1
            col = ix % 8
            return ButtonInput(zero_index_row=row, zero_index_col=col)
        elif message.note >= 32 and message.note <= 39:
            # Top encoder push
            index = message.note - 32
            return ButtonInput(zero_index_row=0, zero_index_col=index)
    logging.warning("Unhandled MIDI message: %s", message)
    return None

async def handle_midi_input(input, configuration, xair, midiout):
    global CURRENT_LAYER, OSC_CACHE

    if isinstance(input, LayerSwitchInput):
        new_layer = input.layer_index
        await create_osc_cache(configuration, xair)
        await switch_layer(new_layer, configuration, midiout)
    elif isinstance(input, ButtonInput):
        if input.row == 0:
            # Top encoder push
            try:
                # Check if top encoder enabled
                enabled = configuration['layers'][CURRENT_LAYER]['enable_zero'].get(bool)
                if not enabled:
                    return
            except confuse.NotFoundError:
                return

            layer = configuration['layers'][CURRENT_LAYER]
            encoders = layer['encoders'].get(confuse.Sequence(confuse.Optional(str)))

            address = encoders[input.col]
            if address:
                xair.put(address, [ 0.750 ])
        elif input.row == 1:
            # Top button push
            layer = configuration['layers'][CURRENT_LAYER]
            buttons = layer['buttons'].get(confuse.Sequence(confuse.Optional(str)))

            address = buttons[input.col]
            if address:
                value = not OSC_CACHE.get(address, False)
                xair.put(address, [int(value)])


def make_stream():
    loop = asyncio.get_event_loop()
    queue = asyncio.Queue()

    def callback(message):
        loop.call_soon_threadsafe(queue.put_nowait, message)

    async def stream():
        while True:
            yield await queue.get()

    return callback, stream()

async def monitor_midi(stream, output_queue: asyncio.Queue):
    async for message in stream:
        try:
            input_event = midi_to_input(message)
            logging.debug(f"MIDI IN: {message} -> {input_event}")
            await output_queue.put(input_event)
        except Exception as exc:
            logging.error("Failed to process MIDI message %s: %s", message, exc)
            continue

async def midi_event_handler(configuration, xair, midiout, queue):
    while True:
        input_event = await queue.get()
        try:
            await handle_midi_input(input_event, configuration, xair, midiout)
        except Exception as exc:
            logging.error(f"Failed to handle MIDI input {input_event}: {exc}")
            continue

async def osc_queue(queue):
    while True:
        try:
            message = await asyncio.wait_for(queue.get(), timeout=None)

            if message.address in ACTIVE_KEYS:
                OSC_CACHE[message.address] = message.arguments[0]
                yield message
        except Exception as exc:
            logging.error(f"Failed to process OSC message: {exc}")
            await asyncio.sleep(0.2)
            continue

async def osc_handler(configuration, xair, midiout):
    with xair.subscribe(meters=True) as stream:
        while True:
            try:
                message = await asyncio.wait_for(stream.get(), timeout=None)

                if message.address in ACTIVE_KEYS:
                    OSC_CACHE[message.address] = message.arguments[0]
                    osc_to_midi(message.address, message.arguments[0], configuration, midiout)
            except Exception as exc:
                logging.error(f"Failed to process OSC message in handler: {exc}")
                await asyncio.sleep(0.2)

def osc_to_midi(address, value, configuration, midiout):
    global OSC_CACHE, CURRENT_LAYER

    layer = configuration['layers'][CURRENT_LAYER]

    buttons = layer['buttons'].get(confuse.Sequence(confuse.Optional(str)))
    encoders = layer['encoders'].get(confuse.Sequence(confuse.Optional(str)))

    if address in buttons:
        ix = buttons.index(address)
        note = BUTTON_IXES[ix]

        try:
            if layer['invert_buttons'].get(bool):
                value = not value
        except confuse.NotFoundError:
            pass

        velocity = 127 if value else 0
        midi_msg = mido.Message('note_on', channel=0, note=note, velocity=velocity)
        logging.debug(f"OSC to MIDI: {address}={value} -> {midi_msg}")
        midiout.send(midi_msg)
    
    if address in encoders:
        ix = encoders.index(address)

        try:
            style_name = layer['encoder_style'].get(str)
            base, span = ENCODER_STYLES[style_name]
        except confuse.NotFoundError:
            base, span = ENCODER_STYLES['single']
        except KeyError:
            base, span = ENCODER_STYLES['single']
            logging.warning(f"Unknown encoder style: {style_name}")

        control = 48 + ix

        new_value = base + max(0, min(span, round(value * span)))

        midi_msg = mido.Message('control_change', channel=0, control=control, value=new_value)
        logging.debug(f"OSC to MIDI: {address}={value} -> {midi_msg}")
        midiout.send(midi_msg)

async def refresh_layer_with_cache(configuration, midiout):
    global OSC_CACHE

    logging.info("Refreshing values to MIDI")

    for key, value in OSC_CACHE.items():
        osc_to_midi(key, value, configuration, midiout)

async def switch_layer(new_layer, configuration, midiout):
    global CURRENT_LAYER

    CURRENT_LAYER = new_layer
    logging.info(f"Switching to layer {CURRENT_LAYER}")

    for ix, button in enumerate(LAYER_BUTTONS):
        note = button
        velocity = 127 if ix == CURRENT_LAYER else 0
        midi_msg = mido.Message('note_on', channel=0, note=note, velocity=velocity)
        logging.debug(f"Layer button MIDI: layer={CURRENT_LAYER} -> {midi_msg}")
        midiout.send(midi_msg)

    await refresh_layer_with_cache(configuration, midiout)

def load_config(path: Path):
    cfg = confuse.Configuration('event-depot', __name__)
    if path and path.exists():
        cfg.set_file(str(path))
    return cfg

async def my_awesome_print_something_every_1_second_task(outputport):
    while True:
        print("Hello from my awesome task!")
        outputport.send(mido.Message('note_on', note=60, velocity=64))
        await asyncio.sleep(1)

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

    midiin = midiout = None
    try:
        xair = pyxair.XAir(pyxair.XInfo("10.20.0.216", 10024, "IRREL", "IRREL", "IRREL"))
        await xair.connect()
        xair.enable_remote()
        status = await xair.get("/status")
        logger.info("X-Air status: %s", status)

        cb, stream = make_stream()

        try:
            logging.info("Opening input  '%s'", input_name)
            input = mido.open_input(input_name, callback=cb)

            logging.info("Opening output '%s'", output_name)
            midiout = mido.open_output(output_name)
        except (IOError, OSError) as exc:
            logging.error("Failed to open MIDI device '%s': %s", input_name, exc)
            raise

        xair_task = xair.start()

        await create_osc_cache(cfg, xair)

        await switch_layer(0, cfg, midiout)

        osc_task = asyncio.create_task(osc_handler(cfg, xair, midiout))

        midi_queue = asyncio.Queue()
        midi_input_task = asyncio.create_task(monitor_midi(stream, midi_queue))
        midi_handle_task = asyncio.create_task(midi_event_handler(cfg, xair, midiout, midi_queue))

        await asyncio.gather(
            midi_input_task,
            midi_handle_task,
            xair_task,
            osc_task,
            # midi_task,
            # my_awesome_print_something_every_1_second_task(midiout)
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception:
        logger.exception("Unhandled error")
        return 4
    finally:
        if midiin:
            midiin.close()
        if midiout:
            midiout.close()

    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))