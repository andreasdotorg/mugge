MIDI_DECK_CC_CODES = {
    0x00: ("volume", "slider"),
    0x01: ("filter", "slider"),
    0x02: ("eq_low", "slider"),
    0x03: ("eq_mid", "slider"),
    0x04: ("eq_high", "slider"),
    0x08: ("pitch", "slider"),
    0x0A: ("jogwheel", "encoder"),
}

# MIDI CC to control mapping (typical Hercules mapping)
MIDI_CC_MAP = {
    # Deck A controls (Channel 1)
    **{
        (1, code): (f"deck_a_{name}", ctype)
        for code, (name, ctype) in MIDI_DECK_CC_CODES.items()
    },
    # Deck B controls (Channel 2)
    **{
        (2, code): (f"deck_b_{name}", ctype)
        for code, (name, ctype) in MIDI_DECK_CC_CODES.items()
    },
    # Generic controls (Channel 0)
    (0, 0x00): ("crossfader", "slider"),
    (0, 0x01): ("browse_encoder", "encoder"),
    (0, 0x03): ("master_volume", "slider"),
}


MIDI_NOTE_CODES = {
    0x07: "play",
    0x06: "cue",
    0x05: "sync",
    0x04: "shift",
    15: "hotcue",
    16: "loop",
    17: "fx",
    18: "neural"
}

MIDI_PAD_NOTE_CODES = {
    0x00: "pads_1",
    0x01: "pads_2",
    0x02: "pads_3",
    0x03: "pads_4",
    0x04: "pads_5",
    0x05: "pads_6",
    0x06: "pads_7",
    0x07: "pads_8",
}

# MIDI Note to button mapping
MIDI_NOTE_MAP = {
    # Deck A buttons (Channel 1)
    **{(1, code): f"deck_a_{name}" for code, name in MIDI_NOTE_CODES.items()},
    # Deck B buttons (Channel 2)
    **{(2, code): f"deck_b_{name}" for code, name in MIDI_NOTE_CODES.items()},
    # Deck A pads (Channel 6)
    **{(6, code): f"deck_a_{name}" for code, name in MIDI_PAD_NOTE_CODES.items()},
    **{(6, code + 8): f"deck_a_sh_{name}" for code, name in MIDI_PAD_NOTE_CODES.items()},
    # Deck B pads (Channel 7)
    **{(7, code): f"deck_b_{name}" for code, name in MIDI_PAD_NOTE_CODES.items()},
    **{(7, code + 8): f"deck_b_sh_{name}" for code, name in MIDI_PAD_NOTE_CODES.items()},

    # Browser and other buttons
    (0, 0x00): "browse_push",
    (1, 0x0D): "load_a",
    (2, 0x0D): "load_b",
    (1, 0x08): "jog_push_a",
    (2, 0x08): "jog_push_b",
    (1, 0x0C): "ph_a",
    (2, 0x0C): "ph_b",
}
