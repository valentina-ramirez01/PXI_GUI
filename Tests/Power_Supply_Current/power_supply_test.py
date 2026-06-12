import nidcpower
import time
import numpy as np


def run_power_supply_current_test(
    smu1_resource,
    smu2_resource,
    voltage_level,
    max_quiescent_current,
    max_test_current=50e-3,
    sample_count=30,
    sample_delay=0.01
):

    smu1 = None
    smu2 = None

    try:

        smu1 = nidcpower.Session(smu1_resource, reset=False)
        smu2 = nidcpower.Session(smu2_resource, reset=False)

        # ---------------- SMU1 ----------------

        smu1.output_function = nidcpower.OutputFunction.DC_VOLTAGE
        smu1.voltage_level_range = max(abs(voltage_level) * 2, 10.0)
        smu1.current_limit = max_test_current
        smu1.voltage_level = -abs(voltage_level)
        smu1.output_enabled = True

        # ---------------- SMU2 ----------------

        smu2.output_function = nidcpower.OutputFunction.DC_VOLTAGE
        smu2.voltage_level_range = max(abs(voltage_level) * 2, 10.0)
        smu2.current_limit = max_test_current
        smu2.voltage_level = abs(voltage_level)
        smu2.output_enabled = True

        smu1.initiate()
        smu2.initiate()

        time.sleep(1)

        smu1_currents = []
        smu2_currents = []

        print("\n==============================")
        print("QUIESCENT CURRENT TEST")
        print("==============================")

        for i in range(sample_count):

            m1 = smu1.measure_multiple()[0]
            m2 = smu2.measure_multiple()[0]

            smu1_currents.append(abs(m1.current))
            smu2_currents.append(abs(m2.current))

            print(
                f"Sample {i+1:02d}: "
                f"SMU1={1000*m1.current:.6f} mA | "
                f"SMU2={1000*m2.current:.6f} mA"
            )

            time.sleep(sample_delay)

        smu1_avg = float(np.mean(smu1_currents))
        smu2_avg = float(np.mean(smu2_currents))

        smu1_std = float(np.std(smu1_currents))
        smu2_std = float(np.std(smu2_currents))

        print("\n------------------------------")
        print("FINAL RESULTS")
        print("------------------------------")

        print(
            f"SMU1 Avg Current = {1000*smu1_avg:.6f} mA "
            f"(Ïƒ={1000*smu1_std:.6f} mA)"
        )

        print(
            f"SMU2 Avg Current = {1000*smu2_avg:.6f} mA "
            f"(Ïƒ={1000*smu2_std:.6f} mA)"
        )

        smu1_pass = smu1_avg <= max_quiescent_current
        smu2_pass = smu2_avg <= max_quiescent_current

        overall_pass = smu1_pass and smu2_pass

        return {

            "smu1_voltage": float(m1.voltage),
            "smu1_current_ma": smu1_avg * 1000,
            "smu1_pass": smu1_pass,

            "smu2_voltage": float(m2.voltage),
            "smu2_current_ma": smu2_avg * 1000,
            "smu2_pass": smu2_pass,

            "overall_pass": overall_pass
        }

    finally:

        try:
            if smu1:
                smu1.output_enabled = False
                smu1.close()
        except:
            pass

        try:
            if smu2:
                smu2.output_enabled = False
                smu2.close()
        except:
            pass



