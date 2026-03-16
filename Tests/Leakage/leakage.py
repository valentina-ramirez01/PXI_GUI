import nidcpower
import numpy as np
import time

# ---------------- CONFIGURATION ----------------

CURRENT_LIMIT = 1e-3          # 1 mA compliance to protect DUT
LEAKAGE_LIMIT = 51e-6         # 10 uA pass/fail limit

SAMPLE_COUNT = 30             # Real measurements used for result
DUMMY_COUNT = 5               # Throwaway readings to let current settle

INITIAL_SETTLE_DELAY = 1.0    # Wait after forcing voltage before any reading
MEASURE_DELAY = 0.1           # Delay between each reading

SMU_RESOURCE = "SMU"          # Change if NI MAX shows a different resource name


# ---------------- LEAKAGE TEST FUNCTION ----------------

def leakage_test(session, voltage_level, test_name):
    """
    Force voltage on DUT pin and measure leakage current.
    PASS/FAIL is based on average current magnitude.
    """

    currents = []

    # Configure SMU
    session.source_mode = nidcpower.SourceMode.SINGLE_POINT
    session.output_function = nidcpower.OutputFunction.DC_VOLTAGE
    session.current_limit = CURRENT_LIMIT
    session.voltage_level = voltage_level
    session.output_enabled = True

    # Let DUT and SMU settle after changing voltage
    time.sleep(INITIAL_SETTLE_DELAY)

    with session.initiate():

        # Throw away a few initial readings
        for _ in range(DUMMY_COUNT):
            time.sleep(MEASURE_DELAY)
            session.measure(nidcpower.MeasurementTypes.CURRENT)

        # Real measurements
        for _ in range(SAMPLE_COUNT):
            time.sleep(MEASURE_DELAY)
            current = session.measure(nidcpower.MeasurementTypes.CURRENT)
            currents.append(current)

    session.output_enabled = False

    currents = np.array(currents)

    avg_current = np.mean(currents)
    min_current = np.min(currents)
    max_current = np.max(currents)

    if abs(avg_current) > LEAKAGE_LIMIT:
        status = "FAIL"
    else:
        status = "PASS"

    return {
        "test": test_name,
        "forced_voltage_V": voltage_level,
        "status": status,
        "avg_current_A": avg_current,
        "avg_current_uA": avg_current * 1e6,
        "min_current_A": min_current,
        "min_current_uA": min_current * 1e6,
        "max_current_A": max_current,
        "max_current_uA": max_current * 1e6
    }


# ---------------- MAIN SCRIPT ----------------

with nidcpower.Session(SMU_RESOURCE, reset=True) as session:

    # Ask user for VDD for leakage-high test
    vdd = float(input("Enter VDD voltage for Input Leakage High test: "))

    print("\nRunning Input Leakage High Test...")
    high_result = leakage_test(
        session,
        voltage_level=vdd,
        test_name="Input Leakage High"
    )
    print("Result:", high_result)

    time.sleep(1.0)

    print("\nRunning Input Leakage Low Test...")
    low_result = leakage_test(
        session,
        voltage_level=0.0,
        test_name="Input Leakage Low"
    )
    print("Result:", low_result)

print("\nTest Complete")
