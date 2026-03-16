import nidcpower
import time

HOLD_TIME = 10  # seconds

with nidcpower.Session("PXI4110", reset=True) as supply:

    ch = supply.channels["0"]

    ch.voltage_level = 5.0
    ch.current_limit = 0.01
    ch.output_enabled = True

    print("Supply enabled. Measure voltage now.")

    start = time.time()

    while time.time() - start < HOLD_TIME:
        time.sleep(0.1)  # small sleep to avoid CPU spinning

    ch.output_enabled = False

    print("Supply disabled.")