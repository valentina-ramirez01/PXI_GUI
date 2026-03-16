import time
import numpy as np
import nidcpower


# ---------------- DEFAULT CONFIGURATION ----------------

CURRENT_LIMIT = 1e-3          # 1 mA compliance to protect DUT input
LEAKAGE_LIMIT = 10e-6         # 10 uA pass/fail limit

SAMPLE_COUNT = 30             # Real measurements used for result
DUMMY_COUNT = 5               # Throwaway readings to let current settle

INITIAL_SETTLE_DELAY = 1.0    # Wait after forcing voltage before reading
MEASURE_DELAY = 0.1           # Delay between readings
SUPPLY_SETTLE_DELAY = 1.0     # Wait after powering DUT

SMU_RESOURCE = "SMU"          # Change if needed from NI MAX
PS_RESOURCE = "PXI4110"       # Change if needed from NI MAX
PS_CHANNEL = "1"              # Power supply channel used for DUT VDD
PS_CURRENT_LIMIT = 0.1        # DUT supply current limit


# ---------------- SESSION HELPERS ----------------

def open_instrument_sessions(
    smu_resource=SMU_RESOURCE,
    ps_resource=PS_RESOURCE,
    reset=True
):
    """
    Open and return power supply and SMU sessions.
    """
    ps_session = nidcpower.Session(ps_resource, reset=reset)
    smu_session = nidcpower.Session(smu_resource, reset=reset)
    return ps_session, smu_session


def close_instrument_sessions(ps_session=None, smu_session=None):
    """
    Safely close sessions.
    """
    if smu_session is not None:
        try:
            smu_session.close()
        except Exception:
            pass

    if ps_session is not None:
        try:
            ps_session.close()
        except Exception:
            pass


# ---------------- POWER SUPPLY FUNCTIONS ----------------

def enable_dut_supply(
    ps_session,
    vdd,
    ps_channel=PS_CHANNEL,
    current_limit=PS_CURRENT_LIMIT
):
    """
    Enable PXI-4110 to power the DUT.
    Returns the selected power supply channel object.
    """
    ch = ps_session.channels[ps_channel]

    ch.voltage_level = float(vdd)
    ch.current_limit = float(current_limit)
    ch.output_enabled = True
    ch.output_connected = True

    return ch


def read_dut_supply(ps_channel_obj):
    """
    Read DUT supply voltage and current.
    """
    measured_v = ps_channel_obj.measure(nidcpower.MeasurementTypes.VOLTAGE)
    measured_i = ps_channel_obj.measure(nidcpower.MeasurementTypes.CURRENT)

    return {
        "measured_voltage_V": measured_v,
        "measured_current_A": measured_i
    }


def disable_dut_supply(ps_session, ps_channel=PS_CHANNEL):
    """
    Fully disable DUT supply output.
    """
    ch = ps_session.channels[ps_channel]

    try:
        ch.voltage_level = 0.0
        time.sleep(0.2)
    except Exception:
        pass

    ch.output_enabled = False
    ch.output_connected = False

    return {
        "channel": ps_channel,
        "status": "OFF"
    }


# ---------------- SMU CONFIGURATION ----------------

def configure_smu_for_leakage(
    smu_session,
    voltage_level,
    current_limit=CURRENT_LIMIT
):
    """
    Configure SMU to force voltage and measure current.
    """
    smu_session.source_mode = nidcpower.SourceMode.SINGLE_POINT
    smu_session.output_function = nidcpower.OutputFunction.DC_VOLTAGE
    smu_session.current_limit = float(current_limit)
    smu_session.voltage_level = float(voltage_level)
    smu_session.output_enabled = True


def disable_smu_output(smu_session):
    """
    Disable SMU output.
    """
    smu_session.output_enabled = False


# ---------------- MEASUREMENT HELPERS ----------------

def collect_leakage_currents(
    smu_session,
    sample_count=SAMPLE_COUNT,
    dummy_count=DUMMY_COUNT,
    initial_settle_delay=INITIAL_SETTLE_DELAY,
    measure_delay=MEASURE_DELAY
):
    """
    Collect leakage current samples from the SMU.
    Returns a NumPy array of currents.
    """
    currents = []

    time.sleep(initial_settle_delay)

    with smu_session.initiate():
        # Throw away initial readings
        for _ in range(dummy_count):
            time.sleep(measure_delay)
            smu_session.measure(nidcpower.MeasurementTypes.CURRENT)

        # Real measurements
        for _ in range(sample_count):
            time.sleep(measure_delay)
            current = smu_session.measure(nidcpower.MeasurementTypes.CURRENT)
            currents.append(current)

    return np.array(currents, dtype=float)


def analyze_leakage_data(
    currents,
    voltage_level,
    test_name,
    leakage_limit=LEAKAGE_LIMIT
):
    """
    Analyze measured currents and return a result dictionary.
    """
    avg_current = float(np.mean(currents))
    min_current = float(np.min(currents))
    max_current = float(np.max(currents))

    status = "NOT PASSED" if abs(avg_current) > leakage_limit else "PASSED"

    return {
        "test": test_name,
        "forced_voltage_V": float(voltage_level),
        "status": status,
        "limit_uA": leakage_limit * 1e6,
        "avg_current_A": avg_current,
        "avg_current_uA": avg_current * 1e6,
        "min_current_A": min_current,
        "min_current_uA": min_current * 1e6,
        "max_current_A": max_current,
        "max_current_uA": max_current * 1e6,
        "sample_count": len(currents)
    }


# ---------------- LEAKAGE TEST FUNCTIONS ----------------

def run_single_leakage_test(
    smu_session,
    voltage_level,
    test_name,
    current_limit=CURRENT_LIMIT,
    leakage_limit=LEAKAGE_LIMIT,
    sample_count=SAMPLE_COUNT,
    dummy_count=DUMMY_COUNT,
    initial_settle_delay=INITIAL_SETTLE_DELAY,
    measure_delay=MEASURE_DELAY
):
    """
    Run one leakage test at a specified forced voltage.
    """
    configure_smu_for_leakage(
        smu_session=smu_session,
        voltage_level=voltage_level,
        current_limit=current_limit
    )

    try:
        currents = collect_leakage_currents(
            smu_session=smu_session,
            sample_count=sample_count,
            dummy_count=dummy_count,
            initial_settle_delay=initial_settle_delay,
            measure_delay=measure_delay
        )

        result = analyze_leakage_data(
            currents=currents,
            voltage_level=voltage_level,
            test_name=test_name,
            leakage_limit=leakage_limit
        )
        return result

    finally:
        disable_smu_output(smu_session)


def run_input_leakage_high(smu_session, vdd, **kwargs):
    """
    Run input leakage high test by forcing the DUT input to VDD.
    """
    return run_single_leakage_test(
        smu_session=smu_session,
        voltage_level=vdd,
        test_name="Input Leakage High",
        **kwargs
    )


def run_input_leakage_low(smu_session, **kwargs):
    """
    Run input leakage low test by forcing the DUT input to 0 V.
    """
    return run_single_leakage_test(
        smu_session=smu_session,
        voltage_level=0.0,
        test_name="Input Leakage Low",
        **kwargs
    )


def run_full_leakage_test(
    vdd,
    smu_resource=SMU_RESOURCE,
    ps_resource=PS_RESOURCE,
    ps_channel=PS_CHANNEL,
    ps_current_limit=PS_CURRENT_LIMIT,
    smu_current_limit=CURRENT_LIMIT,
    leakage_limit=LEAKAGE_LIMIT,
    sample_count=SAMPLE_COUNT,
    dummy_count=DUMMY_COUNT,
    initial_settle_delay=INITIAL_SETTLE_DELAY,
    measure_delay=MEASURE_DELAY,
    supply_settle_delay=SUPPLY_SETTLE_DELAY,
    reset=True
):
    """
    Full leakage test sequence:
    1. Open sessions
    2. Power DUT
    3. Run leakage high
    4. Run leakage low
    5. Power DUT down
    6. Close sessions

    Returns a structured results dictionary for easy GUI use.
    """
    ps_session = None
    smu_session = None
    results = {
        "power_up": None,
        "input_leakage_high": None,
        "input_leakage_low": None,
        "power_down": None,
        "error": None
    }

    try:
        ps_session, smu_session = open_instrument_sessions(
            smu_resource=smu_resource,
            ps_resource=ps_resource,
            reset=reset
        )

        ps_channel_obj = enable_dut_supply(
            ps_session=ps_session,
            vdd=vdd,
            ps_channel=ps_channel,
            current_limit=ps_current_limit
        )

        with ps_session.initiate():
            time.sleep(supply_settle_delay)

            results["power_up"] = read_dut_supply(ps_channel_obj)

            results["input_leakage_high"] = run_input_leakage_high(
                smu_session=smu_session,
                vdd=vdd,
                current_limit=smu_current_limit,
                leakage_limit=leakage_limit,
                sample_count=sample_count,
                dummy_count=dummy_count,
                initial_settle_delay=initial_settle_delay,
                measure_delay=measure_delay
            )

            time.sleep(1.0)

            results["input_leakage_low"] = run_input_leakage_low(
                smu_session=smu_session,
                current_limit=smu_current_limit,
                leakage_limit=leakage_limit,
                sample_count=sample_count,
                dummy_count=dummy_count,
                initial_settle_delay=initial_settle_delay,
                measure_delay=measure_delay
            )

    except Exception as e:
        results["error"] = str(e)

    finally:
        if ps_session is not None:
            try:
                results["power_down"] = disable_dut_supply(
                    ps_session=ps_session,
                    ps_channel=ps_channel
                )
            except Exception as e:
                results["power_down"] = {
                    "channel": ps_channel,
                    "status": "ERROR",
                    "message": str(e)
                }

        close_instrument_sessions(ps_session=ps_session, smu_session=smu_session)

    return results


# ---------------- OPTIONAL PRINT HELPER ----------------

def print_leakage_results(results):
    """
    Pretty-print results to console.
    Useful for standalone testing.
    """
    if results.get("error"):
        print("\nTest Error:")
        print(results["error"])
        return

    power_up = results.get("power_up")
    if power_up:
        print("\nDUT Supply ON:")
        print(f"  Voltage: {power_up['measured_voltage_V']:.3f} V")
        print(f"  Current: {power_up['measured_current_A']:.6f} A")

    high = results.get("input_leakage_high")
    if high:
        print("\nInput Leakage High:")
        print(f"  Status: {high['status']}")
        print(f"  Forced Voltage: {high['forced_voltage_V']:.3f} V")
        print(f"  Avg Current: {high['avg_current_uA']:.3f} uA")
        print(f"  Min Current: {high['min_current_uA']:.3f} uA")
        print(f"  Max Current: {high['max_current_uA']:.3f} uA")
        print(f"  Limit: {high['limit_uA']:.3f} uA")

    low = results.get("input_leakage_low")
    if low:
        print("\nInput Leakage Low:")
        print(f"  Status: {low['status']}")
        print(f"  Forced Voltage: {low['forced_voltage_V']:.3f} V")
        print(f"  Avg Current: {low['avg_current_uA']:.3f} uA")
        print(f"  Min Current: {low['min_current_uA']:.3f} uA")
        print(f"  Max Current: {low['max_current_uA']:.3f} uA")
        print(f"  Limit: {low['limit_uA']:.3f} uA")

    power_down = results.get("power_down")
    if power_down:
        print("\nDUT Supply OFF:")
        print(f"  Channel: {power_down['channel']}")
        print(f"  Status: {power_down['status']}")


# ---------------- MAIN ----------------

def main():
    vdd = float(input("Enter DUT VDD voltage: "))

    results = run_full_leakage_test(vdd=vdd)
    print_leakage_results(results)

    print("\nTest Complete")


if __name__ == "__main__":
    main()