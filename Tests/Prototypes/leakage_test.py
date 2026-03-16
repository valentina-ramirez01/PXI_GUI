import nidcpower
import time

HOLD_TIME = 10  # seconds

with nidcpower.Session("PXI4110", reset=True) as supply:
    ch = supply.channels["1"]

    ch.voltage_level = 5.0
    ch.current_limit = 0.1
    ch.output_enabled = True
    ch.output_connected = True

    print("Supply enabled. Measure voltage now.")

    with supply.initiate():
        start = time.time()

        while time.time() - start < HOLD_TIME:
            v = ch.measure(nidcpower.MeasurementTypes.VOLTAGE)
            i = ch.measure(nidcpower.MeasurementTypes.CURRENT)
            print(f"Voltage: {v:.3f} V   Current: {i:.6f} A")
            time.sleep(0.5)

    ch.output_enabled = False
    print("Supply disabled.")