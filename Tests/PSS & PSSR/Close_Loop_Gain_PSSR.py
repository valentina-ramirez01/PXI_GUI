import nidcpower
import nidmm
import time
import numpy as np


def set_vin(ch, v, settle_time):
    ch.voltage_level = float(v)
    time.sleep(settle_time)


def read_vout_avg(dmm, n_samples):
    samples = []

    for i in range(n_samples):
        try:
            v = float(dmm.read())
            samples.append(v)
            print(f"DMM Sample {i+1:02d}: {v:.9f} V")
        except Exception as e:
            print(f"DMM sample {i+1} failed: {e}")

        time.sleep(0.01)

    if len(samples) == 0:
        raise RuntimeError("No valid DMM samples collected")

    return float(np.mean(samples)), float(np.std(samples))


def run_closed_loop_gain(
    psu_resource,
    smu1_resource,
    smu2_resource,
    dmm_resource,
    psu_channel,
    vin0,
    vin1,
    sample_count,
    settle_time=0.5
):

    with nidcpower.Session(psu_resource, reset=True) as psu, \
         nidcpower.Session(smu1_resource, reset=True) as smu1, \
         nidcpower.Session(smu2_resource, reset=True) as smu2, \
         nidmm.Session(dmm_resource) as dmm:

        # ---------------- DMM ----------------
        dmm.configure_measurement_digits(
            nidmm.Function.DC_VOLTS,
            10.0,
            6.5
        )

        # ---------------- PSU (VIN) ----------------
        vin_ch = psu.channels[psu_channel]

        vin_ch.output_function = nidcpower.OutputFunction.DC_VOLTAGE
        vin_ch.current_limit = 0.1
        vin_ch.output_enabled = True
        vin_ch.output_connected = True

        psu.initiate()

        # ---------------- SMU Rails ----------------
        smu1.output_function = nidcpower.OutputFunction.DC_VOLTAGE
        smu2.output_function = nidcpower.OutputFunction.DC_VOLTAGE

        smu1.voltage_level = -5.0
        smu2.voltage_level = 5.0

        smu1.current_limit = 0.05
        smu2.current_limit = 0.05

        smu1.output_enabled = True
        smu2.output_enabled = True

        smu1.initiate()
        smu2.initiate()

        print("\n==============================")
        print("CLOSED LOOP GAIN TEST START")
        print("==============================\n")

        # ======================================================
        # VIN0
        # ======================================================
        print(f"\nSetting VIN = {vin0} V")
        set_vin(vin_ch, vin0, settle_time)

        vout0_mean, vout0_std = read_vout_avg(dmm, sample_count)

        print(f"\nVIN={vin0} V â†’ VOUT={vout0_mean:.6f} V (Ïƒ={vout0_std:.6f})")

        # ======================================================
        # VIN1
        # ======================================================
        print(f"\nSetting VIN = {vin1} V")
        set_vin(vin_ch, vin1, settle_time)

        vout1_mean, vout1_std = read_vout_avg(dmm, sample_count)

        print(f"\nVIN={vin1} V â†’ VOUT={vout1_mean:.6f} V (Ïƒ={vout1_std:.6f})")

        # ======================================================
        # GAIN
        # ======================================================
        gain = (vout1_mean - vout0_mean) / (vin1 - vin0)

        print("\n==============================")
        print("FINAL RESULT")
        print("==============================")
        print(f"VOUT({vin0}V) = {vout0_mean:.6f} V")
        print(f"VOUT({vin1}V) = {vout1_mean:.6f} V")
        print(f"Closed-loop Gain = {gain:.6f} V/V")

        return gain
