import nidcpower
import nidmm
import time
import numpy as np
import math


def run_pss_test(
    smu_neg_resource,
    smu_pos_resource,
    dmm_resource,
    sample_delay,
    sample_count,
    psu_resource,
    voltage_start=5,
    voltage_stop=10,
    voltage_step=1,
    settling_time=1,
    max_test_current=50e-3,
    dmm_voltage_range=2,
    dmm_timeout=2.0,
):

    def generate_sweep(start, stop, step):
        values = []
        v = start
        while v <= stop + 1e-12:
            values.append(round(v, 6))
            v += step
        return values

    smu_neg = None
    smu_pos = None
    dmm = None

    try:
        print("\n==============================")
        print("PSS TEST START")
        print("==============================")

        psu = nidcpower.Session(psu_resource, reset=False)
        vin_ch = psu.channels["0"]
        vin_ch.output_function = nidcpower.OutputFunction.DC_VOLTAGE
        vin_ch.voltage_level = 0.0
        vin_ch.current_limit = 0.1
        vin_ch.output_enabled = True

        dmm = nidmm.Session(dmm_resource)
        dmm.configure_measurement_digits(
            nidmm.Function.DC_VOLTS,
            dmm_voltage_range,
            6.5
        )

        smu_neg = nidcpower.Session(smu_neg_resource, reset=True)
        smu_pos = nidcpower.Session(smu_pos_resource, reset=True)

        for smu in (smu_neg, smu_pos):
            smu.source_mode = nidcpower.SourceMode.SINGLE_POINT
            smu.output_function = nidcpower.OutputFunction.DC_VOLTAGE
            smu.voltage_level_range = voltage_stop * 1.5
            smu.current_limit = max_test_current
            smu.output_enabled = True

        supply_values = generate_sweep(voltage_start, voltage_stop, voltage_step)

        vout_avg = []
        vout_std = []

        psu.initiate()
        smu_pos.initiate()
        smu_neg.initiate()

        for v in supply_values:

            print(f"\nSupply = Â±{v:.3f} V")

            smu_pos.voltage_level = v
            smu_neg.voltage_level = -v

            time.sleep(settling_time)

            samples = []

            for i in range(sample_count):
                try:
                    val = float(dmm.read(dmm_timeout))
                    print(f"  Sample {i+1:02d}: {val:.9f} V")
                    samples.append(val)
                except Exception as e:
                    print(f"  Sample {i+1:02d} ERROR: {e}")

                time.sleep(sample_delay)

            if len(samples) == 0:
                raise RuntimeError("No valid DMM samples collected")

            vout_avg.append(np.mean(samples))
            vout_std.append(np.std(samples))

        slope, intercept = np.polyfit(supply_values, vout_avg, 1)

        pss_v_per_v = abs(slope)
        pss_uv_per_v = pss_v_per_v * 1e6
        pss_db = 20 * math.log10(pss_v_per_v) if pss_v_per_v > 0 else float("-inf")

        return {
            "supply": supply_values,
            "vout_avg": vout_avg,
            "vout_std": vout_std,
            "slope": slope,
            "intercept": intercept,
            "pss_uv_per_v": pss_uv_per_v,
            "pss_db": pss_db,
        }

    finally:
        try:
            if smu_pos:
                smu_pos.voltage_level = 0
                smu_pos.output_enabled = False
                smu_pos.close()
        except:
            pass

        try:
            if smu_neg:
                smu_neg.voltage_level = 0
                smu_neg.output_enabled = False
                smu_neg.close()
        except:
            pass

        try:
            if dmm:
                dmm.close()
        except:
            pass
