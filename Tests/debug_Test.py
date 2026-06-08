import time
import numpy as np
import matplotlib.pyplot as plt

import nifgen
import niscope


# =========================
# Resources
# =========================
FGEN_RESOURCE = "Func_Gen"
SCOPE_RESOURCE = "Scope"

SCOPE_CHANNEL = "1"   # change to "1" if connected to CH1


# =========================
# Test Settings
# =========================
FREQUENCY = 1000       # Hz
FGEN_AMPLITUDE = 0.1   # NI-FGEN may interpret this as Vpeak, not Vpp
DC_OFFSET = 0.0

SCOPE_RANGE = 1.0
SAMPLE_RATE = 10e6
NUM_SAMPLES = 10000


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


def main():
    fgen = None
    scope = None

    try:
        print("Opening instruments...")
        fgen = nifgen.Session(FGEN_RESOURCE)
        scope = niscope.Session(SCOPE_RESOURCE)

        print("Configuring function generator...")
        fgen.output_mode = nifgen.OutputMode.FUNC

        fgen.configure_standard_waveform(
            waveform=nifgen.Waveform.SINE,
            amplitude=FGEN_AMPLITUDE,
            dc_offset=DC_OFFSET,
            frequency=FREQUENCY,
            start_phase=0.0
        )

        fgen.output_enabled = True
        fgen.initiate()

        time.sleep(0.5)

        print("Configuring oscilloscope...")
        scope.configure_horizontal_timing(
            min_sample_rate=SAMPLE_RATE,
            min_num_pts=NUM_SAMPLES,
            ref_position=50.0,
            num_records=1,
            enforce_realtime=False
        )

        scope.channels[SCOPE_CHANNEL].configure_vertical(
            range=SCOPE_RANGE,
            coupling=niscope.VerticalCoupling.DC,
            probe_attenuation=1.0,
            enabled=True
        )

        scope.configure_trigger_immediate()
        scope.initiate()

        print("Fetching waveform...")
        waveform = scope.channels[SCOPE_CHANNEL].fetch(
            num_samples=NUM_SAMPLES,
            timeout=10.0
        )

        data = waveform_to_array(waveform)

        v_min = np.min(data)
        v_max = np.max(data)
        v_pp = v_max - v_min
        v_avg = np.mean(data)
        v_rms = np.sqrt(np.mean(data ** 2))

        print("\n========== RESULTS ==========")
        print("Scope Channel:", SCOPE_CHANNEL)
        print("Frequency Set:", FREQUENCY, "Hz")
        print("FGEN Amplitude Setting:", FGEN_AMPLITUDE)
        print("Min Voltage:", v_min, "V")
        print("Max Voltage:", v_max, "V")
        print("Vpp:", v_pp, "V")
        print("Average:", v_avg, "V")
        print("RMS:", v_rms, "V")
        print("=============================\n")

        time_axis = np.arange(len(data)) / SAMPLE_RATE

        plt.figure()
        plt.plot(time_axis, data)
        plt.title("PXIe-5413 Output Measured by PXIe-5114")
        plt.xlabel("Time [s]")
        plt.ylabel("Voltage [V]")
        plt.grid(True)
        plt.show()

    except Exception as e:
        print("\nTEST ERROR:")
        print(e)

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


if __name__ == "__main__":
    main()