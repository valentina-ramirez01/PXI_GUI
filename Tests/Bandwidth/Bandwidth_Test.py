import nifgen
import niscope
import nidcpower
import numpy as np
import time
import matplotlib.pyplot as plt

# =========================
# RESOURCES
# =========================
FGEN_RESOURCE = "AWG"
SCOPE_RESOURCE = "Oscilloscope"
PSU_RESOURCE = "PSU"

# =========================
# SWEEP SETTINGS
# =========================
F_START = 1e3
F_STOP = 10e6
N_POINTS = 50

N_AVG = 15
SETTLE_TIME = 0.1

AMP = 1.0
OFFSET = 0.0

# =========================
# DERIVED SWEEP
# =========================
freqs = np.logspace(np.log10(F_START), np.log10(F_STOP), N_POINTS)

# =========================
# INSTRUMENTS
# =========================
psu = nidcpower.Session(PSU_RESOURCE, reset=True)
fgen = nifgen.Session(FGEN_RESOURCE)
fgen.reset()
scope = niscope.Session(SCOPE_RESOURCE)
scope.reset()

# =========================
# PSU SETUP (±15V)
# =========================
for ch, v in [(psu.channels["1"], 15.0), (psu.channels["2"], -15.0)]:
    ch.output_function = nidcpower.OutputFunction.DC_VOLTAGE
    ch.voltage_level_range = 20.0
    ch.current_limit = 0.1
    ch.voltage_level = v
    ch.output_enabled = True

psu.initiate()

# =========================
# FGEN SETUP (FIXED WAVEFORM APPROACH)
# =========================
fgen.output_mode = nifgen.OutputMode.FUNC

# We'll overwrite frequency each step (simplest + stable)
fgen.func_waveform = nifgen.Waveform.SINE
fgen.func_amplitude = AMP
fgen.func_dc_offset = OFFSET

fgen.initiate()

# =========================
# SCOPE SETUP
# =========================
scope.configure_vertical(
    range=2.0,
    coupling=niscope.VerticalCoupling.DC
)

scope.configure_trigger_immediate()

gain = []

# =========================
# SWEEP LOOP
# =========================
print("Starting stepped sine sweep...")

for f in freqs:

    print(f"Testing {f/1e6:.3f} MHz")

    # update fgen frequency
    fgen.func_frequency = float(f)

    time.sleep(SETTLE_TIME)

    samples = []

    for _ in range(N_AVG):

        scope.abort()
        scope.initiate()

        w0 = scope.channels["0"].fetch(
            num_samples=4096,
            timeout=10.0
        )[0]

        data = np.array(w0.samples)

        # discard edges (VERY IMPORTANT for sine measurements)
        mid = len(data) // 4
        data = data[mid:-mid]

        samples.append(data)

    ch0 = np.mean(np.array(samples), axis=0)

    # RMS magnitude (robust for sine sweep)
    rms_vals = []

    for _ in range(N_AVG):

        scope.abort()
        scope.initiate()

        w0 = scope.channels["0"].fetch(
            num_samples=4096,
            timeout=10.0
        )[0]

        data = np.array(w0.samples)

        # discard edges
        mid = len(data) // 4
        data = data[mid:-mid]

        rms_vals.append(np.sqrt(np.mean(data**2)))

    v_rms = np.mean(rms_vals)

    gain.append(v_rms)

# =========================
# NORMALIZE RESPONSE
# =========================
gain = np.array(gain)
gain_db = 20 * np.log10(gain / gain[0])

# =========================
# FIND -3 dB BANDWIDTH
# =========================
idx = np.where(gain_db <= -3)[0]
bw = freqs[idx[0]] if len(idx) else None

# =========================
# RESULTS
# =========================
print("\n===== RESULT =====")
if bw:
    print(f"-3 dB bandwidth ≈ {bw/1e6:.3f} MHz")
else:
    print("No -3 dB point found")

# =========================
# PLOT
# =========================
plt.figure()
plt.semilogx(freqs, gain_db, marker="o")
plt.axhline(-3, linestyle="--")

if bw:
    plt.axvline(bw, linestyle="--")

plt.title("Stepped Sine Bandwidth (CH0 only, averaged)")
plt.xlabel("Frequency (Hz)")
plt.ylabel("Gain (dB)")
plt.grid(True, which="both")
plt.tight_layout()
plt.show()

# =========================
# CLEANUP
# =========================
fgen.abort()
psu.close()