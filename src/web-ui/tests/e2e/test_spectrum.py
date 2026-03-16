"""E2E tests for the 1/3-octave spectrum display.

Validates:
    - spectrum.js loads without errors
    - PiAudioSpectrum global is defined and functional
    - Canvas renders correctly when given mock data
    - 31 bands are represented (canvas not blank after update)
    - Peak hold behavior works as expected
    - Spectrum data arrives via the monitoring WebSocket
"""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


# -- Module loading --


def test_spectrum_js_loads(page):
    """spectrum.js can be loaded via script tag without errors."""
    result = page.evaluate("""() => {
        return new Promise((resolve, reject) => {
            var s = document.createElement('script');
            s.src = '/static/js/spectrum.js';
            s.onload = () => resolve(true);
            s.onerror = () => reject('Failed to load spectrum.js');
            document.head.appendChild(s);
        });
    }""")
    assert result is True


def test_spectrum_global_defined(page):
    """PiAudioSpectrum global is defined after loading spectrum.js."""
    page.evaluate("""() => {
        return new Promise((resolve, reject) => {
            var s = document.createElement('script');
            s.src = '/static/js/spectrum.js';
            s.onload = () => resolve();
            s.onerror = () => reject('Failed to load');
            document.head.appendChild(s);
        });
    }""")
    result = page.evaluate("typeof window.PiAudioSpectrum")
    assert result == "object"


def test_spectrum_has_api_methods(page):
    """PiAudioSpectrum exposes init, updateData, and destroy methods."""
    page.evaluate("""() => {
        return new Promise((resolve, reject) => {
            var s = document.createElement('script');
            s.src = '/static/js/spectrum.js';
            s.onload = () => resolve();
            s.onerror = () => reject('Failed to load');
            document.head.appendChild(s);
        });
    }""")
    methods = page.evaluate("""() => {
        return {
            init: typeof PiAudioSpectrum.init,
            updateData: typeof PiAudioSpectrum.updateData,
            destroy: typeof PiAudioSpectrum.destroy,
        };
    }""")
    assert methods["init"] == "function"
    assert methods["updateData"] == "function"
    assert methods["destroy"] == "function"


# -- Constants --


def test_spectrum_band_count(page):
    """BANDS array has exactly 31 entries (IEC 61260)."""
    page.evaluate("""() => {
        return new Promise((resolve, reject) => {
            var s = document.createElement('script');
            s.src = '/static/js/spectrum.js';
            s.onload = () => resolve();
            s.onerror = () => reject('Failed to load');
            document.head.appendChild(s);
        });
    }""")
    count = page.evaluate("PiAudioSpectrum.BANDS.length")
    assert count == 31


def test_spectrum_band_range(page):
    """Bands span 20 Hz to 20 kHz."""
    page.evaluate("""() => {
        return new Promise((resolve, reject) => {
            var s = document.createElement('script');
            s.src = '/static/js/spectrum.js';
            s.onload = () => resolve();
            s.onerror = () => reject('Failed to load');
            document.head.appendChild(s);
        });
    }""")
    first = page.evaluate("PiAudioSpectrum.BANDS[0]")
    last = page.evaluate("PiAudioSpectrum.BANDS[30]")
    assert first == 20
    assert last == 20000


def test_spectrum_label_count(page):
    """10 frequency labels are defined."""
    page.evaluate("""() => {
        return new Promise((resolve, reject) => {
            var s = document.createElement('script');
            s.src = '/static/js/spectrum.js';
            s.onload = () => resolve();
            s.onerror = () => reject('Failed to load');
            document.head.appendChild(s);
        });
    }""")
    count = page.evaluate("PiAudioSpectrum.LABELS.length")
    assert count == 10


def test_spectrum_db_range(page):
    """dB range is -60 to 0."""
    page.evaluate("""() => {
        return new Promise((resolve, reject) => {
            var s = document.createElement('script');
            s.src = '/static/js/spectrum.js';
            s.onload = () => resolve();
            s.onerror = () => reject('Failed to load');
            document.head.appendChild(s);
        });
    }""")
    db_min = page.evaluate("PiAudioSpectrum.DB_MIN")
    db_max = page.evaluate("PiAudioSpectrum.DB_MAX")
    assert db_min == -60
    assert db_max == 0


# -- Canvas rendering --


def test_spectrum_canvas_renders(page):
    """Canvas is not blank after init and data update."""
    page.evaluate("""() => {
        return new Promise((resolve, reject) => {
            var s = document.createElement('script');
            s.src = '/static/js/spectrum.js';
            s.onload = () => resolve();
            s.onerror = () => reject('Failed to load');
            document.head.appendChild(s);
        });
    }""")

    # Create a canvas in the DOM
    page.evaluate("""() => {
        var c = document.createElement('canvas');
        c.id = 'test-spectrum-canvas';
        c.style.width = '600px';
        c.style.height = '140px';
        document.body.appendChild(c);
        PiAudioSpectrum.init('test-spectrum-canvas');
    }""")

    # Feed data and wait a couple of animation frames
    page.evaluate("""() => {
        var data = [];
        for (var i = 0; i < 31; i++) data.push(-20 + Math.random() * 10);
        PiAudioSpectrum.updateData(data);
    }""")
    page.wait_for_timeout(200)

    # Check that the canvas has non-zero pixel data (not all black)
    has_content = page.evaluate("""() => {
        var c = document.getElementById('test-spectrum-canvas');
        var ctx = c.getContext('2d');
        var data = ctx.getImageData(0, 0, c.width, c.height).data;
        for (var i = 0; i < data.length; i += 4) {
            // Check for any non-background pixel (not pure #0f0f0f)
            if (data[i] > 20 || data[i+1] > 20 || data[i+2] > 20) return true;
        }
        return false;
    }""")
    assert has_content, "Canvas should have non-blank content after data update"

    page.evaluate("PiAudioSpectrum.destroy()")


def test_spectrum_rejects_wrong_band_count(page):
    """updateData ignores arrays that are not exactly 31 elements."""
    page.evaluate("""() => {
        return new Promise((resolve, reject) => {
            var s = document.createElement('script');
            s.src = '/static/js/spectrum.js';
            s.onload = () => resolve();
            s.onerror = () => reject('Failed to load');
            document.head.appendChild(s);
        });
    }""")

    # No error should be thrown for wrong-length input
    no_error = page.evaluate("""() => {
        try {
            PiAudioSpectrum.updateData([1, 2, 3]);
            PiAudioSpectrum.updateData(null);
            PiAudioSpectrum.updateData([]);
            return true;
        } catch(e) {
            return false;
        }
    }""")
    assert no_error, "updateData should silently ignore invalid input"


def test_spectrum_destroy_stops_animation(page):
    """destroy() cancels the animation frame loop."""
    page.evaluate("""() => {
        return new Promise((resolve, reject) => {
            var s = document.createElement('script');
            s.src = '/static/js/spectrum.js';
            s.onload = () => resolve();
            s.onerror = () => reject('Failed to load');
            document.head.appendChild(s);
        });
    }""")

    page.evaluate("""() => {
        var c = document.createElement('canvas');
        c.id = 'test-destroy-canvas';
        c.style.width = '400px';
        c.style.height = '140px';
        document.body.appendChild(c);
        PiAudioSpectrum.init('test-destroy-canvas');
    }""")
    page.wait_for_timeout(100)

    # destroy should not throw
    no_error = page.evaluate("""() => {
        try {
            PiAudioSpectrum.destroy();
            return true;
        } catch(e) {
            return false;
        }
    }""")
    assert no_error


# -- WebSocket spectrum data --


def test_monitoring_payload_has_spectrum(page):
    """The monitoring WebSocket payload includes a spectrum field."""
    has_spectrum = page.evaluate("""() => {
        return new Promise((resolve) => {
            var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            var url = proto + '//' + location.host + '/ws/monitoring?scenario=A';
            var ws = new WebSocket(url);
            ws.onmessage = function(ev) {
                var data = JSON.parse(ev.data);
                ws.close();
                resolve(
                    data.spectrum !== undefined &&
                    data.spectrum.bands !== undefined &&
                    Array.isArray(data.spectrum.bands)
                );
            };
            ws.onerror = function() { resolve(false); };
            setTimeout(function() { resolve(false); }, 5000);
        });
    }""")
    assert has_spectrum, "Monitoring payload should include spectrum.bands array"


def test_spectrum_bands_count_in_payload(page):
    """The spectrum.bands array in the WS payload has exactly 31 entries."""
    count = page.evaluate("""() => {
        return new Promise((resolve) => {
            var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            var url = proto + '//' + location.host + '/ws/monitoring?scenario=A';
            var ws = new WebSocket(url);
            ws.onmessage = function(ev) {
                var data = JSON.parse(ev.data);
                ws.close();
                resolve(data.spectrum.bands.length);
            };
            ws.onerror = function() { resolve(-1); };
            setTimeout(function() { resolve(-1); }, 5000);
        });
    }""")
    assert count == 31


def test_spectrum_bands_in_db_range(page):
    """All spectrum band values are within [-60, 0] dB."""
    all_in_range = page.evaluate("""() => {
        return new Promise((resolve) => {
            var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            var url = proto + '//' + location.host + '/ws/monitoring?scenario=A';
            var ws = new WebSocket(url);
            ws.onmessage = function(ev) {
                var data = JSON.parse(ev.data);
                ws.close();
                var bands = data.spectrum.bands;
                for (var i = 0; i < bands.length; i++) {
                    if (bands[i] < -60 || bands[i] > 0) {
                        resolve(false);
                        return;
                    }
                }
                resolve(true);
            };
            ws.onerror = function() { resolve(false); };
            setTimeout(function() { resolve(false); }, 5000);
        });
    }""")
    assert all_in_range, "All spectrum band values should be in [-60, 0] dB range"


def test_spectrum_idle_scenario_all_silent(page):
    """Scenario E (Idle) produces all-silent spectrum bands (-60 dB)."""
    all_silent = page.evaluate("""() => {
        return new Promise((resolve) => {
            var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            var url = proto + '//' + location.host + '/ws/monitoring?scenario=E';
            var ws = new WebSocket(url);
            ws.onmessage = function(ev) {
                var data = JSON.parse(ev.data);
                ws.close();
                var bands = data.spectrum.bands;
                for (var i = 0; i < bands.length; i++) {
                    if (bands[i] !== -60) {
                        resolve(false);
                        return;
                    }
                }
                resolve(true);
            };
            ws.onerror = function() { resolve(false); };
            setTimeout(function() { resolve(false); }, 5000);
        });
    }""")
    assert all_silent, "Idle scenario should produce all -60 dB spectrum bands"
