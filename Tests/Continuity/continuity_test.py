import nidcpower
import numpy as np
import time

# --- Configuration ---
VOLTAGE_LIMIT = 1.0  # Protect SMU
CURRENT_START = 100e-9  # 100 nA
CURRENT_STOP = 2e-3     # 2 mA
CURRENT_POINTS = 30
SAMPLE_COUNT = 30
SETTLE_DELAY = 0.05     # Delay before each measurement
CURRENT_SWITCH_DELAY = 1.0  # Delay before reversing current direction

# --- Sweep function ---
def sweep_until_target(session, input_pin, positive=True):
    """
    Sweep current logarithmically until |diode voltage| is within target window.
    Takes SAMPLE_COUNT measurements only when voltage is in target range.
    Returns pass/fail status, average, and current at target.
    """
    VOLTAGE_MIN_PASS = 0.6
    VOLTAGE_MAX_PASS = 0.8
    currents = np.logspace(np.log10(CURRENT_START), np.log10(CURRENT_STOP), CURRENT_POINTS)
    if not positive:
        currents = -currents
        VOLTAGE_MIN_PASS = -0.8
        VOLTAGE_MAX_PASS = -0.6

    # Configure SMU
    session.source_mode = nidcpower.SourceMode.SINGLE_POINT
    session.output_function = nidcpower.OutputFunction.DC_CURRENT
    session.voltage_limit = VOLTAGE_LIMIT
    session.output_enabled = True

    result = None

    for current in currents:
        session.current_level = current
        time.sleep(0.5)  # allow diode to settle

        # Measure single voltage to check pass/fail window
        with session.initiate():
            voltage = session.measure(nidcpower.MeasurementTypes.VOLTAGE)

        abs_voltage = voltage  # Use absolute value for threshold check


        if VOLTAGE_MIN_PASS <= abs_voltage <= VOLTAGE_MAX_PASS:
            # Take SAMPLE_COUNT measurements now that diode is in target range
            voltages = []
            with session.initiate():
                for _ in range(SAMPLE_COUNT):
                    time.sleep(SETTLE_DELAY)
                    voltages.append(session.measure(nidcpower.MeasurementTypes.VOLTAGE))
            avg_v = np.mean(voltages)
            result = {
                "status": "PASS",
                "avg_voltage": avg_v,
                "current_to_target": current
            }
            break
    else:
        # Never reached target window
        with session.initiate():
            voltage = session.measure(nidcpower.MeasurementTypes.VOLTAGE)
        result = {
            "status": "FAIL",
            "reason": f"Did not reach {VOLTAGE_MIN_PASS} V within {CURRENT_STOP*1e3:.0f} mA",
            "voltage": voltage,
            "current_to_target": currents[-1]
        }

    session.output_enabled = False
    return result

# --- Main script ---
with nidcpower.Session("SMU", reset=True) as session:
    # Forward sweep (positive current)
    forward_result = sweep_until_target(session, input_pin="IN+")
    print("Forward Sweep Result:", forward_result)

    # Delay before reverse sweep9*
    time.sleep(CURRENT_SWITCH_DELAY)

    # Reverse sweep (negative current)
    reverse_result = sweep_until_target(session, input_pin="IN+", positive=False)
    print("Reverse Sweep Result:", reverse_result)