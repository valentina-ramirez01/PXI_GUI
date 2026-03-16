import nidcpower
import numpy as np
import time

SAMPLES = 30
CURRENT = 100e-6  # 100 µA
VOLTAGE_LIMIT = 1.0  # Limit to protect SMU
HOLD_TIME = 7  # seconds

def measure_esd_diode(session, input_pin, smu_lo, current_level):
    """Measure the ESD diode for a given input pin and SMU LO connection, holding current for 3 seconds."""
    session.current_level = current_level
    voltages = []
    with session.initiate():
        session.output_enabled = True
        # Hold current for HOLD_TIME seconds while sampling voltage
        start_time = time.time()
        while time.time() - start_time < HOLD_TIME:
            voltage = session.measure(nidcpower.MeasurementTypes.VOLTAGE)
            voltages.append(voltage)
            time.sleep(HOLD_TIME / SAMPLES)  # sample evenly over HOLD_TIME
        session.output_enabled = False
    avg_voltage = np.mean(voltages)
    return avg_voltage

with nidcpower.Session("SMU", reset=True) as session:
    session.source_mode = nidcpower.SourceMode.SINGLE_POINT
    session.output_function = nidcpower.OutputFunction.DC_CURRENT
    session.voltage_limit = VOLTAGE_LIMIT

    # Test diode to V− (GND / 0V)
    avg_forward = measure_esd_diode(session, input_pin="IN+", smu_lo="V-", current_level=CURRENT)
    print(f"Diode to V−: Average Voltage = {avg_forward:.6f} V")
    if 0.65 <= abs(avg_forward) <= 0.75:
        print("Diode to V− PASS")
    else:
        print("Diode to V− FAIL")

    # Test diode to V+ (0V)
    avg_reverse = measure_esd_diode(session, input_pin="IN+", smu_lo="V+", current_level=-CURRENT)
    print(f"Diode to V+: Average Voltage = {avg_reverse:.6f} V")
    if 0.65 <= abs(avg_reverse) <= 0.75:
        print("Diode to V+ PASS")
    else:
        print("Diode to V+ FAIL")