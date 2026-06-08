import time
import numpy as np
import matplotlib.pyplot as plt

import nifgen
import niscope


FGEN_RESOURCE = "Func_Gen"
SCOPE_RESOURCE = "Scope"

VOUT_CHANNEL = "1"    # CH1 = OPA551 OUT

FREQUENCY = 1000      # 1 kHz
AMPLITUDE = 0.01      # Vpeak = 0.1 Vpp
OFFSET = 0.0

SAMPLE_RATE = 10e6
NUM_SAMPLES = 20000

VIN_RANGE = 0.5
VOUT_RANGE = 2.0      # expected output ≈ 1 Vpp


def waveform_to_array(waveform):
    if hasattr(waveform, "samples"):
        return np.array(waveform.samples, dtype=float)

    if isinstance(waveform, list):
        data = []
        for item in waveform:
            if hasattr(item, "samples"):
                data.extend(item.samples)
            elif isinstance(item, (list, tuple, np.ndarray)):
                data.extend(item)
            else:
                data.append(item)
        return np.array(data, dtype=float)

    return np.array(waveform, dtype=float)


def vpp(data):
    data = np.array(data, dtype=float)
    return np.max(data) - np.min(data)


fgen = None
scope = None

try:
    fgen = nifgen.Session(FGEN_RESOURCE)
    scope = niscope.Session(SCOPE_RESOURCE)

    fgen.output_mode = nifgen.OutputMode.FUNC
    fgen.configure_standard_waveform(
        waveform=nifgen.Waveform.SINE,
        amplitude=AMPLITUDE,
        dc_offset=OFFSET,
        frequency=FREQUENCY,
        start_phase=0.0
    )
    fgen.output_enabled = True
    fgen.initiate()

    time.sleep(0.5)

    scope.configure_horizontal_timing(
        min_sample_rate=SAMPLE_RATE,
        min_num_pts=NUM_SAMPLES,
        ref_position=50.0,
        num_records=1,
        enforce_realtime=False
    )



    scope.channels[VOUT_CHANNEL].configure_vertical(
        range=VOUT_RANGE,
        coupling=niscope.VerticalCoupling.DC,
        probe_attenuation=1.0,
        enabled=True
    )

    scope.configure_trigger_immediate()
    scope.initiate()

    vout_waveform = scope.channels[VOUT_CHANNEL].fetch(
        num_samples=NUM_SAMPLES,
        timeout=10.0
    )


    vout = waveform_to_array(vout_waveform)

    vout_pp = vpp(vout)

    print("\n========== OPA551 1 kHz AC Gain Check ==========")
    print("Vout Vpp = {:.6f} V".format(vout_pp))
    print("Expected Vin  ≈ 0.10 Vpp")
    print("Expected Vout ≈ 1.00 Vpp")
    print("Expected Gain ≈ 10.09 V/V")
    print("================================================\n")

    t = np.arange(len(vout)) / SAMPLE_RATE

    plt.figure()
    plt.plot(t[:5000], vout[:5000], label="CH1 Vout")
    plt.title("OPA551 1 kHz Input and Output Waveforms")
    plt.xlabel("Time [s]")
    plt.ylabel("Voltage [V]")
    plt.grid(True)
    plt.legend()
    plt.show()

finally:
    try:
        if fgen is not None:
            fgen.abort()
            fgen.output_enabled = False
            fgen.close()
    except Exception:
        pass

    try:
        if scope is not None:
            scope.close()
    except Exception:
        pass