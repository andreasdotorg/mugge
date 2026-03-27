"""Excursion estimator for speaker driver protection (US-092).

Estimates peak cone excursion from signal level and frequency using the
electromechanical loudspeaker model (Thiele-Small parameters).  Provides
two main functions:

1. estimate_peak_excursion_mm() -- predicted excursion at a given frequency
   and signal level.
2. compute_xmax_safe_level_dbfs() -- maximum safe dBFS at a given frequency
   before exceeding Xmax.

The model assumes a simple second-order high-pass mechanical response:

  Below Fs:  excursion is spring-controlled (flat with frequency)
  At Fs:     excursion peaks (amplified by Qts)
  Above Fs:  excursion falls at 12 dB/oct (mass-controlled)

Transfer function (displacement per unit voltage):

  X(f) = (Bl / Re) / sqrt((k - m*w^2)^2 + (Rm*w)^2)

where:
  k  = 1/Cms  (mechanical stiffness, N/m)
  m  = Mms    (moving mass, kg)
  Rm = mechanical resistance = sqrt(k*m)/Qms  (from Qms definition)
  w  = 2*pi*f
  Bl = force factor (T*m)
  Re = DC resistance (ohm)

This yields peak displacement in meters for 1 Vrms input.  Scale by the
actual voltage to get real excursion.
"""

import math


def _mechanical_params(fs_hz, qts, bl_tm, mms_g, cms_m_per_n):
    """Derive mechanical model parameters from T/S specs.

    Returns (k, m, Rm, w0) where:
      k  = stiffness (N/m)
      m  = moving mass (kg)
      Rm = mechanical resistance (N*s/m)
      w0 = angular resonance frequency (rad/s)
    """
    k = 1.0 / cms_m_per_n          # N/m
    m = mms_g / 1000.0             # kg
    w0 = 2.0 * math.pi * fs_hz

    # Qms = w0 * m / Rm  =>  Rm = w0 * m / Qms
    # But we don't always have Qms separately.  Derive from Qts:
    #   Qts = Qes*Qms/(Qes+Qms),  and Qes = w0*m*Re / (Bl^2)
    # Instead, use the total Q directly for the combined system response.
    # For excursion estimation, the relevant Q is the mechanical Q (Qms)
    # which controls the resonance peak.  However, in a real system the
    # electrical damping also limits excursion.  Using Qts (total Q) gives
    # the correct excursion estimate for a voltage-driven system because
    # electrical damping IS present.
    #
    # Rm_total = w0 * m / Qts  (total damping seen by the cone)
    if qts <= 0:
        raise ValueError(f"qts must be positive, got {qts}")
    Rm = w0 * m / qts

    return k, m, Rm, w0


def estimate_peak_excursion_mm(signal_level_dbfs, frequency_hz,
                                fs_hz, qts, bl_tm, mms_g, cms_m_per_n,
                                re_ohm=None, sd_cm2=None,
                                amp_voltage_gain=42.4,
                                ada8200_0dbfs_vrms=4.9,
                                pw_gain_mult=1.0):
    """Estimate peak cone excursion at a given frequency and signal level.

    Parameters
    ----------
    signal_level_dbfs : float
        Digital signal level in dBFS (0 dBFS = full scale).
    frequency_hz : float
        Signal frequency in Hz (must be > 0).
    fs_hz : float
        Driver free-air resonance frequency (Hz).
    qts : float
        Total Q factor at Fs.
    bl_tm : float
        Force factor (T*m).
    mms_g : float
        Moving mass including air load (grams).
    cms_m_per_n : float
        Mechanical compliance (m/N).
    re_ohm : float or None
        DC voice coil resistance (ohm).  If None, estimated from
        bl_tm, mms_g, cms_m_per_n, fs_hz, qts.
    sd_cm2 : float or None
        Effective piston area (cm^2).  Not used in excursion calc but
        reserved for future volume displacement output.
    amp_voltage_gain : float
        Amplifier voltage gain (V/V).  Default: 42.4.
    ada8200_0dbfs_vrms : float
        DAC output voltage at 0 dBFS (Vrms).  Default: 4.9.
    pw_gain_mult : float
        PipeWire filter-chain gain node multiplier (linear).

    Returns
    -------
    float
        Estimated peak excursion in mm.
    """
    if frequency_hz <= 0:
        raise ValueError(f"frequency_hz must be positive, got {frequency_hz}")
    if bl_tm <= 0:
        raise ValueError(f"bl_tm must be positive, got {bl_tm}")
    if mms_g <= 0:
        raise ValueError(f"mms_g must be positive, got {mms_g}")
    if cms_m_per_n <= 0:
        raise ValueError(f"cms_m_per_n must be positive, got {cms_m_per_n}")
    if pw_gain_mult <= 0:
        raise ValueError(f"pw_gain_mult must be positive, got {pw_gain_mult}")

    # Estimate Re if not provided, from Qes relationship:
    #   Qes = 2*pi*fs * Mms * Re / Bl^2
    # We don't have Qes directly, but we can derive it from Qts and Qms.
    # Without Qms, use a typical Qms=5 assumption to get Qes:
    #   Qes = Qts * Qms / (Qms - Qts)
    # Or just use a reasonable default Re.
    if re_ohm is None:
        # Estimate from T/S: Re = Bl^2 * Qts / (2*pi*fs * Mms * (1 - Qts/Qms_est))
        # With Qms_est=5 (typical): Qes_est = Qts * 5 / (5 - Qts)
        qms_est = 5.0
        if qts >= qms_est:
            # Qts >= Qms is physically implausible; use Bl^2/(2*pi*fs*Mms) as rough Re
            re_ohm = bl_tm ** 2 / (2.0 * math.pi * fs_hz * mms_g / 1000.0)
        else:
            qes_est = qts * qms_est / (qms_est - qts)
            re_ohm = bl_tm ** 2 * qes_est / (2.0 * math.pi * fs_hz * mms_g / 1000.0)
        # Clamp to a reasonable range
        re_ohm = max(re_ohm, 0.1)

    # Voltage at speaker terminals
    v_0dbfs = ada8200_0dbfs_vrms * amp_voltage_gain  # V at 0 dBFS
    v_rms = v_0dbfs * pw_gain_mult * 10.0 ** (signal_level_dbfs / 20.0)

    # Mechanical parameters
    k, m, Rm, w0 = _mechanical_params(fs_hz, qts, bl_tm, mms_g, cms_m_per_n)

    # Driving force per volt: F = Bl * I = Bl * V / Ze
    # At low frequencies Ze ~ Re (ignoring Le which is small below a few kHz)
    w = 2.0 * math.pi * frequency_hz
    force_amplitude = bl_tm * v_rms / re_ohm

    # Mechanical impedance: Zm = Rm + j*(w*m - k/w)
    # |Zm| = sqrt(Rm^2 + (w*m - k/w)^2)
    reactance = w * m - k / w
    zm_magnitude = math.sqrt(Rm ** 2 + reactance ** 2)

    # Peak displacement (meters) = F / |Zm| (velocity/w gives displacement)
    # Actually: x = F / (w * |Zm|) is wrong.
    # Correct: displacement amplitude = force / |mechanical impedance in displacement terms|
    # The equation of motion: m*x'' + Rm*x' + k*x = F*sin(wt)
    # Steady state: X = F / sqrt((k - m*w^2)^2 + (Rm*w)^2)
    stiffness_term = k - m * w ** 2
    damping_term = Rm * w
    displacement_denominator = math.sqrt(stiffness_term ** 2 + damping_term ** 2)

    x_peak_m = force_amplitude / displacement_denominator

    # Convert to mm, multiply by sqrt(2) for peak from RMS
    x_peak_mm = x_peak_m * 1000.0 * math.sqrt(2)

    return x_peak_mm


def compute_xmax_safe_level_dbfs(frequency_hz, xmax_mm,
                                  fs_hz, qts, bl_tm, mms_g, cms_m_per_n,
                                  re_ohm=None, sd_cm2=None,
                                  amp_voltage_gain=42.4,
                                  ada8200_0dbfs_vrms=4.9,
                                  pw_gain_mult=1.0):
    """Compute the maximum safe dBFS at a given frequency before exceeding Xmax.

    This is the inverse of estimate_peak_excursion_mm: find the signal level
    that produces exactly xmax_mm of peak excursion.

    Parameters
    ----------
    frequency_hz : float
        Frequency in Hz.
    xmax_mm : float
        Maximum linear excursion (mm).
    fs_hz, qts, bl_tm, mms_g, cms_m_per_n : float
        Thiele-Small parameters (see estimate_peak_excursion_mm).
    re_ohm : float or None
        DC resistance.  Estimated if None.
    sd_cm2 : float or None
        Piston area (reserved).
    amp_voltage_gain : float
        Amplifier voltage gain.
    ada8200_0dbfs_vrms : float
        DAC output at 0 dBFS.
    pw_gain_mult : float
        PW gain node multiplier.

    Returns
    -------
    float
        Maximum safe signal level in dBFS.  Will be <= 0.
    """
    if xmax_mm <= 0:
        raise ValueError(f"xmax_mm must be positive, got {xmax_mm}")
    if frequency_hz <= 0:
        raise ValueError(f"frequency_hz must be positive, got {frequency_hz}")

    # Strategy: compute excursion at 0 dBFS, then scale.
    # Excursion is linear with voltage, voltage is linear with dBFS.
    x_at_0dbfs = estimate_peak_excursion_mm(
        signal_level_dbfs=0.0,
        frequency_hz=frequency_hz,
        fs_hz=fs_hz, qts=qts, bl_tm=bl_tm,
        mms_g=mms_g, cms_m_per_n=cms_m_per_n,
        re_ohm=re_ohm, sd_cm2=sd_cm2,
        amp_voltage_gain=amp_voltage_gain,
        ada8200_0dbfs_vrms=ada8200_0dbfs_vrms,
        pw_gain_mult=pw_gain_mult,
    )

    if x_at_0dbfs <= 0:
        return 0.0  # Should not happen with valid inputs

    # excursion scales linearly with voltage, voltage = 10^(dBFS/20)
    # xmax = x_at_0dbfs * 10^(level/20)
    # level = 20 * log10(xmax / x_at_0dbfs)
    ratio = xmax_mm / x_at_0dbfs
    if ratio >= 1.0:
        return 0.0  # Xmax is not exceeded even at 0 dBFS
    return 20.0 * math.log10(ratio)


def generate_xmax_limit_curve(freq_min_hz, freq_max_hz, num_points,
                               xmax_mm,
                               fs_hz, qts, bl_tm, mms_g, cms_m_per_n,
                               re_ohm=None, sd_cm2=None,
                               amp_voltage_gain=42.4,
                               ada8200_0dbfs_vrms=4.9,
                               pw_gain_mult=1.0):
    """Generate a frequency-dependent Xmax limit curve.

    Returns arrays of frequencies and corresponding maximum safe dBFS values.

    Parameters
    ----------
    freq_min_hz : float
        Start frequency (Hz).
    freq_max_hz : float
        End frequency (Hz).
    num_points : int
        Number of points (log-spaced).
    xmax_mm : float
        Maximum linear excursion (mm).
    fs_hz, qts, bl_tm, mms_g, cms_m_per_n, re_ohm, sd_cm2 : various
        Driver T/S parameters.
    amp_voltage_gain, ada8200_0dbfs_vrms, pw_gain_mult : float
        Signal chain parameters.

    Returns
    -------
    tuple of (list[float], list[float])
        (frequencies_hz, max_safe_dbfs) -- parallel arrays.
    """
    if freq_min_hz <= 0 or freq_max_hz <= 0:
        raise ValueError("Frequencies must be positive")
    if freq_min_hz >= freq_max_hz:
        raise ValueError("freq_min_hz must be less than freq_max_hz")
    if num_points < 2:
        raise ValueError("num_points must be >= 2")

    log_min = math.log10(freq_min_hz)
    log_max = math.log10(freq_max_hz)
    step = (log_max - log_min) / (num_points - 1)

    freqs = []
    levels = []
    for i in range(num_points):
        f = 10.0 ** (log_min + i * step)
        level = compute_xmax_safe_level_dbfs(
            frequency_hz=f, xmax_mm=xmax_mm,
            fs_hz=fs_hz, qts=qts, bl_tm=bl_tm,
            mms_g=mms_g, cms_m_per_n=cms_m_per_n,
            re_ohm=re_ohm, sd_cm2=sd_cm2,
            amp_voltage_gain=amp_voltage_gain,
            ada8200_0dbfs_vrms=ada8200_0dbfs_vrms,
            pw_gain_mult=pw_gain_mult,
        )
        freqs.append(f)
        levels.append(level)

    return freqs, levels
