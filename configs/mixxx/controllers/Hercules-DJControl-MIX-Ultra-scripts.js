// Hercules-DJControl-MIX-Ultra-scripts.js
//
// Mixxx mapping script for the Hercules DJControl MIX Ultra (USB-MIDI).
// Based on the DJControl MIX mapping by DJ Phatso / Kerrick Staley.
// Adapted for Ultra hardware differences using djercula MIDI reference.
//
// Changes from stock MIX script:
//   - Function prefix: DJCMIXULTRA (was DJCMIX)
//   - Per-deck shift buttons (Ultra has shift per deck, not global)
//   - Removed vinyl button handling (Ultra has no vinyl button)
//   - Shift LED messages updated for per-deck shift

class DJCMixUltraClass {
    constructor() {
        // How fast scratching is.
        this.scratchScale = 1.0;

        // How much faster seeking (shift+scratch) is than scratching.
        this.scratchShiftMultiplier = 4;

        // How fast bending is.
        this.bendScale = 1.0;

        this.kScratchActionNone = 0;
        this.kScratchActionScratch = 1;
        this.kScratchActionSeek = 2;
        this.kScratchActionBend = 3;
    }

    init() {
        if (engine.getValue("[App]", "num_samplers") < 8) {
            engine.setValue("[App]", "num_samplers", 8);
        }

        this.scratchButtonState = true;
        this.scratchAction = {
            1: this.kScratchActionNone,
            2: this.kScratchActionNone
        };

        // Set effects Levels - Dry/Wet
        engine.setParameter("[EffectRack1_EffectUnit1_Effect1]", "meta", 0.6);
        engine.setParameter("[EffectRack1_EffectUnit1_Effect2]", "meta", 0.6);
        engine.setParameter("[EffectRack1_EffectUnit1_Effect3]", "meta", 0.6);
        engine.setParameter("[EffectRack1_EffectUnit2_Effect1]", "meta", 0.6);
        engine.setParameter("[EffectRack1_EffectUnit2_Effect2]", "meta", 0.6);
        engine.setParameter("[EffectRack1_EffectUnit2_Effect3]", "meta", 0.6);
        engine.setParameter("[EffectRack1_EffectUnit1]", "mix", 1);
        engine.setParameter("[EffectRack1_EffectUnit2]", "mix", 1);

        // Ask the controller to send all current knob/slider values over MIDI
        midi.sendShortMsg(0xB0, 0x7F, 0x7F);
    }

    _scratchEnable(deck) {
        const alpha = 1.0 / 8;
        const beta = alpha / 32;
        engine.scratchEnable(deck, 248, 33 + 1 / 3, alpha, beta);
    }

    _convertWheelRotation(value) {
        // When you rotate the jogwheel, the controller always sends either 0x1
        // (clockwise) or 0x7F (counter clockwise). 0x1 should map to 1, 0x7F
        // should map to -1 (IOW it's 7-bit signed).
        return value < 0x40 ? 1 : -1;
    }

    // The touch action on the jog wheel's top surface
    wheelTouch(channel, _control, value, _status, _group) {
        const deck = channel;
        if (value > 0) {
            if (engine.getValue("[Channel" + deck + "]", "play") !== 1 || this.scratchButtonState) {
                this._scratchEnable(deck);
                this.scratchAction[deck] = this.kScratchActionScratch;
            } else {
                this.scratchAction[deck] = this.kScratchActionBend;
            }
        } else {
            engine.scratchDisable(deck);
            this.scratchAction[deck] = this.kScratchActionNone;
        }
    }

    // The touch action on the jog wheel's top surface while holding shift
    wheelTouchShift(channel, _control, value, _status, _group) {
        const deck = channel - 3;
        if (value > 0) {
            this._scratchEnable(deck);
            this.scratchAction[deck] = this.kScratchActionSeek;
        } else {
            engine.scratchDisable(deck);
            this.scratchAction[deck] = this.kScratchActionNone;
        }
    }

    _scratchWheelImpl(deck, value) {
        const interval = this._convertWheelRotation(value);
        const scratchAction = this.scratchAction[deck];

        if (scratchAction === this.kScratchActionScratch) {
            engine.scratchTick(deck, interval * this.scratchScale);
        } else if (scratchAction === this.kScratchActionSeek) {
            engine.scratchTick(deck,
                interval
                * this.scratchScale
                * this.scratchShiftMultiplier);
        } else {
            this._bendWheelImpl(deck, value);
        }
    }

    scratchWheel(channel, _control, value, _status, _group) {
        const deck = channel;
        this._scratchWheelImpl(deck, value);
    }

    scratchWheelShift(channel, _control, value, _status, _group) {
        const deck = channel - 3;
        this._scratchWheelImpl(deck, value);
    }

    _bendWheelImpl(deck, value) {
        const interval = this._convertWheelRotation(value);
        engine.setValue("[Channel" + deck + "]", "jog",
            interval * this.bendScale);
    }

    bendWheel(channel, _control, value, _status, _group) {
        const deck = channel;
        this._bendWheelImpl(deck, value);
    }

    // Cue master button (Shift+PFL on Deck A)
    cueMaster(_channel, _control, value, _status, _group) {
        if (value === 0) {
            return;
        }
        let masterIsCued = engine.getValue("[Master]", "headMix") > 0;
        masterIsCued = !masterIsCued;
        const headMixValue = masterIsCued ? 1 : -1;
        engine.setValue("[Master]", "headMix", headMixValue);
        const cueMasterLedValue = masterIsCued ? 0x7F : 0x00;
        midi.sendShortMsg(0x91, 0x0C, cueMasterLedValue);
    }

    // Cue mix button (Shift+PFL on Deck B), toggles PFL/master split
    cueMix(_channel, _control, value, _status, _group) {
        if (value === 0) {
            return;
        }
        script.toggleControl("[Master]", "headSplit");
        const cueMixLedValue =
            engine.getValue("[Master]", "headSplit") ? 0x7F : 0x00;
        midi.sendShortMsg(0x92, 0x0C, cueMixLedValue);
    }

    // Per-deck shift button handler
    shiftButton(channel, _control, value, _status, _group) {
        if (value >= 0x40) {
            // When Shift is held, light LEDs to show alt function status
            const cueMasterLedValue =
                engine.getValue("[Master]", "headMix") > 0 ? 0x7F : 0x00;
            midi.sendShortMsg(0x91, 0x0C, cueMasterLedValue);
            const cueMixLedValue =
                engine.getValue("[Master]", "headSplit") ? 0x7F : 0x00;
            midi.sendShortMsg(0x92, 0x0C, cueMixLedValue);
        } else {
            // When Shift is released, restore normal PFL LED values
            const cueChan1LedValue =
                engine.getValue("[Channel1]", "pfl") ? 0x7F : 0x00;
            midi.sendShortMsg(0x91, 0x0C, cueChan1LedValue);
            const cueChan2LedValue =
                engine.getValue("[Channel2]", "pfl") ? 0x7F : 0x00;
            midi.sendShortMsg(0x92, 0x0C, cueChan2LedValue);
        }
    }

    shutdown() {
        midi.sendShortMsg(0xB0, 0x7F, 0x00);
    }
}

var DJCMIXULTRA = new DJCMixUltraClass;  // eslint-disable-line no-var, no-unused-vars
