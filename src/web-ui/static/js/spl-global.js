/**
 * Global SPL pipeline — keeps a persistent PCM WebSocket to /ws/pcm/monitor
 * and computes A-weighted SPL from UMIK-1 (ch3) for the Dashboard hero display.
 *
 * Runs independently of which tab is active. The PCM connection opens on app
 * init and stays alive with auto-reconnect. When the Test tab is also using
 * the same PCM source, both pipelines receive data independently (the server
 * supports multiple WebSocket clients on the same source).
 *
 * Registered as a PiAudio global consumer so it initializes at app boot.
 */

"use strict";

(function () {

    var UMIK_SENSITIVITY = 121.4; // dBFS-to-dBSPL offset for UMIK-1
    var FFT_SIZE = 4096;
    var SAMPLE_RATE = 48000;
    var NUM_CHANNELS = 4;
    var UMIK_CHANNEL = 2; // UMIK-1 is pcm-bridge input_3 = port.id 2 (0-based)
    var UPDATE_EVERY = 6; // Throttle DOM writes to ~10 Hz (every 6th rAF at 60fps)

    var pipeline = null;
    var ws = null;
    var connected = false;
    var reconnectTimer = null;
    var animFrame = null;
    var updateCounter = 0;

    // Calibration state (fetched once from backend)
    var calFreqs = null;
    var calDb = null;
    var calBinLUT = null;
    var calEnabled = false;
    var aWeightBinLUT = null;

    // -- Calibration helpers (mirrors test.js T-088-6 / US-096) --

    function fetchCalibration() {
        var xhr = new XMLHttpRequest();
        xhr.open("GET", "/api/v1/test-tool/calibration", true);
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== 4) return;
            if (xhr.status !== 200) return;
            try {
                var data = JSON.parse(xhr.responseText);
                if (!data.frequencies || !data.db_corrections ||
                    data.frequencies.length === 0) return;
                calFreqs = data.frequencies;
                calDb = data.db_corrections;
                buildCalBinLUT();
                buildAWeightBinLUT();
                calEnabled = true;
            } catch (e) {
                // Calibration optional — SPL works uncalibrated (Z-weighted fallback)
            }
        };
        xhr.send();
    }

    function buildCalBinLUT() {
        if (!calFreqs || !calDb || calFreqs.length === 0) {
            calBinLUT = null;
            calEnabled = false;
            return;
        }
        var binCount = FFT_SIZE / 2 + 1;
        var binHz = SAMPLE_RATE / FFT_SIZE;
        calBinLUT = new Float32Array(binCount);
        for (var i = 0; i < binCount; i++) {
            calBinLUT[i] = interpCalDb(i * binHz);
        }
    }

    function interpCalDb(freq) {
        var n = calFreqs.length;
        if (freq <= calFreqs[0]) return calDb[0];
        if (freq >= calFreqs[n - 1]) return calDb[n - 1];
        var lo = 0;
        var hi = n - 1;
        while (hi - lo > 1) {
            var mid = (lo + hi) >> 1;
            if (calFreqs[mid] <= freq) lo = mid;
            else hi = mid;
        }
        var t = (freq - calFreqs[lo]) / (calFreqs[hi] - calFreqs[lo]);
        return calDb[lo] + t * (calDb[hi] - calDb[lo]);
    }

    function aWeightDb(freq) {
        if (freq <= 0) return -200;
        var f2 = freq * freq;
        var num = 148693636 * f2 * f2;
        var denom = (f2 + 424.36)
            * Math.sqrt((f2 + 11599.29) * (f2 + 544496.41))
            * (f2 + 148693636);
        if (denom === 0) return -200;
        var ra = num / denom;
        return 20 * Math.log10(Math.max(ra, 1e-20)) + 2.0;
    }

    function buildAWeightBinLUT() {
        var binCount = FFT_SIZE / 2 + 1;
        var binHz = SAMPLE_RATE / FFT_SIZE;
        aWeightBinLUT = new Float32Array(binCount);
        for (var i = 0; i < binCount; i++) {
            aWeightBinLUT[i] = aWeightDb(i * binHz);
        }
    }

    // -- PCM WebSocket --

    function connectPcm() {
        if (ws) return;
        var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = proto + "//" + window.location.host + "/ws/pcm/monitor";
        try {
            ws = new WebSocket(url);
        } catch (e) {
            scheduleReconnect();
            return;
        }
        ws.binaryType = "arraybuffer";

        ws.onopen = function () {
            connected = true;
        };

        ws.onmessage = function (ev) {
            if (pipeline) {
                pipeline.feedPcmMessage(ev.data, { detectGaps: true });
            }
        };

        ws.onclose = function () {
            connected = false;
            ws = null;
            scheduleReconnect();
        };

        ws.onerror = function () {
            connected = false;
        };
    }

    function scheduleReconnect() {
        if (reconnectTimer) return;
        reconnectTimer = setTimeout(function () {
            reconnectTimer = null;
            connectPcm();
        }, 3000);
    }

    // -- SPL computation + DOM update (runs in rAF loop) --

    function renderLoop() {
        animFrame = requestAnimationFrame(renderLoop);

        if (!pipeline || !connected) return;
        if (!pipeline.dirty) return;

        pipeline.processFFT();
        var rms = pipeline.rmsLinear;
        if (rms <= 0) return;

        // Z-weighted SPL from time-domain RMS
        var splZ = 20 * Math.log10(Math.max(rms, 1e-10)) + UMIK_SENSITIVITY;

        // A-weighted SPL from FFT bins
        var splA = splZ; // Fallback if no cal/A-weight data
        var fd = pipeline.freqData;
        if (fd && aWeightBinLUT && fd.length === aWeightBinLUT.length) {
            var sumPower = 0;
            for (var i = 1; i < fd.length; i++) {
                var binDb = fd[i];
                var calCorr = (calEnabled && calBinLUT && i < calBinLUT.length)
                    ? calBinLUT[i] : 0;
                var correctedDb = binDb - calCorr + aWeightBinLUT[i];
                sumPower += Math.pow(10, correctedDb / 10);
            }
            if (sumPower > 0) {
                splA = 10 * Math.log10(sumPower) + UMIK_SENSITIVITY;
            }
        }

        // Throttle DOM writes
        updateCounter++;
        if (updateCounter < UPDATE_EVERY) return;
        updateCounter = 0;

        var heroEl = document.getElementById("spl-value");
        if (heroEl) {
            heroEl.textContent = Math.round(splA);
            heroEl.style.color = PiAudio.splColorRaw(splA);
        }
    }

    // -- Global consumer interface --

    function init() {
        pipeline = PiAudioFFT.create({
            fftSize: FFT_SIZE,
            sampleRate: SAMPLE_RATE,
            numChannels: NUM_CHANNELS,
            dbMin: -90,
            dbMax: 0,
            smoothing: 0,
            channelIndex: UMIK_CHANNEL
        });

        // Build A-weight LUT immediately (formula-based, no cal needed)
        buildAWeightBinLUT();

        // Fetch UMIK-1 calibration (async, SPL works without it)
        fetchCalibration();

        // Open PCM WebSocket
        connectPcm();

        // Start render loop
        animFrame = requestAnimationFrame(renderLoop);
    }

    PiAudio.registerGlobalConsumer("spl-global", {
        init: init
    });

})();
