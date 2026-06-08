import time
import numpy as np
import matplotlib.pyplot as plt

import nidcpower
import nidmm


# =========================
# Resources
# =========================
PSU_RESOURCE = "PXI4110"      # PXI-4110
SMU_RESOURCE = "SMU"         # PXIe-4138 input source
DMM_RESOURCE = "PXI4080"      # PXIe-4080 DMM


# =========================
# PXI-4110 Channels
# =========================
PSU_POS_CH = "1"   # +15 V
PSU_NEG_CH = "2"   # -15 V


# =========================
# Test Settings
# =========================
VPLUS = 15.0
VMINUS = -15.0

VIN_VALUES = np.array([
    -0.10, -0.075, -0.05, -0.025,
     0.00,
     0.025, 0.05, 0.075, 0.10
])

INPUT_CURRENT_LIMIT = 1e-3
PSU_CURRENT_LIMIT = 0.05

SETTLE_TIME = 0.30
EXPECTED_GAIN = 1 + 10000 / 1100


def configure_4110(psu):
    psu.channels[PSU_POS_CH].voltage_level = VPLUS
    psu.channels[PSU_POS_CH].current_limit = PSU_CURRENT_LIMIT
    psu.channels[PSU_POS_CH].output_enabled = True

    psu.channels[PSU_NEG_CH].voltage_level = VMINUS
    psu.channels[PSU_NEG_CH].current_limit = PSU_CURRENT_LIMIT
    psu.channels[PSU_NEG_CH].output_enabled = True

    psu.initiate()


def configure_smu_input(smu):
    smu.source_mode = nidcpower.SourceMode.SINGLE_POINT
    smu.output_function = nidcpower.OutputFunction.DC_VOLTAGE
    smu.voltage_level = 0.0
    smu.current_limit = INPUT_CURRENT_LIMIT
    smu.output_enabled = True
    smu.initiate()


def configure_dmm_if_possible(dmm):
    try:
        dmm.configure_measurement_digits(
            nidmm.Function.DC_VOLTS,
            10.0,
            5.5
        )
        print("DMM configured with configure_measurement_digits().")
        return
    except Exception as e:
        print("DMM digits config skipped:", e)

    try:
        dmm.configure_measurement_absolute(
            nidmm.Function.DC_VOLTS,
            10.0,
            0.00001
        )
        print("DMM configured with configure_measurement_absolute().")
        return
    except Exception as e:
        print("DMM absolute config skipped:", e)

    print("Using DMM default configuration.")


psu = None
smu = None
dmm = None

try:
    print("Opening instruments...")
    psu = nidcpower.Session(PSU_RESOURCE, reset=False)
    smu = nidcpower.Session(SMU_RESOURCE, reset=False)
    dmm = nidmm.Session(DMM_RESOURCE)

    print("Configuring ±15 V supplies...")
    configure_4110(psu)
    time.sleep(1.0)

    print("Configuring SMU input...")
    configure_smu_input(smu)
    time.sleep(0.5)

    print("Configuring DMM...")
    configure_dmm_if_possible(dmm)

    vin_measured = []
    vout_measured = []

    print("\n========== OPA551 DC Gain Test ==========")
    print("Expected gain = {:.4f} V/V".format(EXPECTED_GAIN))
    print("Expected gain = {:.2f} dB".format(20 * np.log10(EXPECTED_GAIN)))
    print("-----------------------------------------")

    for vin in VIN_VALUES:
        smu.voltage_level = float(vin)
        time.sleep(SETTLE_TIME)

        samples = []
        for _ in range(5):
            try:
                samples.append(dmm.read())
            except Exception:
                time.sleep(0.1)
            time.sleep(0.05)

        if len(samples) == 0:
            vout = np.nan
        else:
            vout = float(np.mean(samples))

        vin_measured.append(vin)
        vout_measured.append(vout)

        if abs(vin) > 1e-9 and np.isfinite(vout):
            point_gain = vout / vin
            point_gain_text = "{:.4f}".format(point_gain)
        else:
            point_gain_text = "N/A"

        print(
            "Vin = {:+.4f} V | Vout = {:+.6f} V | Point Gain = {}".format(
                vin,
                vout,
                point_gain_text
            )
        )

    vin_measured = np.array(vin_measured, dtype=float)
    vout_measured = np.array(vout_measured, dtype=float)

    valid = np.isfinite(vin_measured) & np.isfinite(vout_measured)

    slope, intercept = np.polyfit(vin_measured[valid], vout_measured[valid], 1)
    gain_db = 20 * np.log10(abs(slope))

    print("-----------------------------------------")
    print("Measured gain from linear fit = {:.4f} V/V".format(slope))
    print("Measured gain = {:.2f} dB".format(gain_db))
    print("Output offset/intercept = {:+.6f} V".format(intercept))
    print("Expected gain = {:.4f} V/V".format(EXPECTED_GAIN))
    print("Expected gain = {:.2f} dB".format(20 * np.log10(EXPECTED_GAIN)))
    print("=========================================\n")

    plt.figure()
    plt.plot(vin_measured, vout_measured, marker="o", label="Measured")
    plt.plot(
        vin_measured,
        slope * vin_measured + intercept,
        linestyle="--",
        label="Linear Fit"
    )
    plt.title("OPA551 DC Closed-Loop Gain Test")
    plt.xlabel("Input Voltage Vin [V]")
    plt.ylabel("Output Voltage Vout [V]")
    plt.grid(True)
    plt.legend()
    plt.show()

except Exception as e:
    print("\nTEST ERROR:")
    print(e)

finally:
    try:
        if smu is not None:
            smu.voltage_level = 0.0
            time.sleep(0.2)
            smu.output_enabled = False
            smu.close()
    except Exception:
        pass

    try:
        if psu is not None:
            psu.channels[PSU_POS_CH].output_enabled = False
            psu.channels[PSU_NEG_CH].output_enabled = False
            psu.close()
    except Exception:
        pass

    try:
        if dmm is not None:
            dmm.close()
    except Exception:
        pass