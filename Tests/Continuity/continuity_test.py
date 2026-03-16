import time
import numpy as np
import nidcpower


# ---------------- DEFAULT CONFIGURATION ----------------

VOLTAGE_LIMIT = 1.0          # Protect SMU
CURRENT_START = 100e-9       # 100 nA
CURRENT_STOP = 1.8e-3          # 1 mA
CURRENT_POINTS = 30
SAMPLE_COUNT = 30
SETTLE_DELAY = 0.05
CURRENT_SWITCH_DELAY = 1.0

FORWARD_VOLTAGE_MIN = 0.6
FORWARD_VOLTAGE_MAX = 0.8
REVERSE_VOLTAGE_MIN = -0.8
REVERSE_VOLTAGE_MAX = -0.6

SMU_RESOURCE = "SMU"


# ---------------- SESSION HELPERS ----------------

def open_smu_session(resource_name=SMU_RESOURCE, reset=True):
    """
    Open and return an SMU session.
    """
    return nidcpower.Session(resource_name, reset=reset)


def close_smu_session(session):
    """
    Safely close an SMU session.
    """
    if session is not None:
        try:
            session.close()
        except Exception:
            pass


# ---------------- CONFIGURATION HELPERS ----------------

def generate_sweep_currents(
    current_start=CURRENT_START,
    current_stop=CURRENT_STOP,
    current_points=CURRENT_POINTS,
    positive=True
):
    """
    Generate logarithmic sweep currents.
    """
    currents = np.logspace(
        np.log10(current_start),
        np.log10(current_stop),
        current_points
    )

    if not positive:
        currents = -currents

    return currents


def configure_smu_for_current_force(session, voltage_limit=VOLTAGE_LIMIT):
    """
    Configure SMU to force current and measure voltage.
    """
    session.source_mode = nidcpower.SourceMode.SINGLE_POINT
    session.output_function = nidcpower.OutputFunction.DC_CURRENT
    session.voltage_limit = float(voltage_limit)
    session.output_enabled = True


def disable_smu_output(session):
    """
    Disable SMU output safely.
    """
    try:
        session.current_level = 0.0
        time.sleep(0.1)
    except Exception:
        pass

    session.output_enabled = False


# ---------------- MEASUREMENT HELPERS ----------------

def measure_voltage_once(session):
    """
    Take a single voltage measurement.
    """
    with session.initiate():
        voltage = session.measure(nidcpower.MeasurementTypes.VOLTAGE)
    return voltage


def measure_voltage_samples(session, sample_count=SAMPLE_COUNT, settle_delay=SETTLE_DELAY):
    """
    Take multiple voltage measurements and return as numpy array.
    """
    voltages = []

    with session.initiate():
        for _ in range(sample_count):
            time.sleep(settle_delay)
            voltages.append(session.measure(nidcpower.MeasurementTypes.VOLTAGE))

    return np.array(voltages, dtype=float)


def analyze_voltage_samples(voltages):
    """
    Return average/min/max statistics for sampled voltages.
    """
    return {
        "avg_voltage": float(np.mean(voltages)),
        "min_voltage": float(np.min(voltages)),
        "max_voltage": float(np.max(voltages)),
        "sample_count": len(voltages)
    }


# ---------------- SWEEP TEST CORE ----------------

def sweep_until_target(
    session,
    input_pin="IN+",
    positive=True,
    voltage_limit=VOLTAGE_LIMIT,
    current_start=CURRENT_START,
    current_stop=CURRENT_STOP,
    current_points=CURRENT_POINTS,
    sample_count=SAMPLE_COUNT,
    settle_delay=SETTLE_DELAY,
    forward_min=FORWARD_VOLTAGE_MIN,
    forward_max=FORWARD_VOLTAGE_MAX,
    reverse_min=REVERSE_VOLTAGE_MIN,
    reverse_max=REVERSE_VOLTAGE_MAX
):
    """
    Sweep current logarithmically until diode voltage enters target window.
    When target is reached, collect sample_count voltage readings and analyze them.
    """
    if positive:
        voltage_min_pass = forward_min
        voltage_max_pass = forward_max
        direction = "FORWARD"
    else:
        voltage_min_pass = reverse_min
        voltage_max_pass = reverse_max
        direction = "REVERSE"

    currents = generate_sweep_currents(
        current_start=current_start,
        current_stop=current_stop,
        current_points=current_points,
        positive=positive
    )

    configure_smu_for_current_force(session, voltage_limit=voltage_limit)

    try:
        for current in currents:
            session.current_level = float(current)
            time.sleep(0.5)

            voltage = measure_voltage_once(session)

            if voltage_min_pass <= voltage <= voltage_max_pass:
                sampled_voltages = measure_voltage_samples(
                    session=session,
                    sample_count=sample_count,
                    settle_delay=settle_delay
                )

                stats = analyze_voltage_samples(sampled_voltages)

                return {
                    "test": f"{direction} DIODE SWEEP",
                    "input_pin": input_pin,
                    "status": "PASS",
                    "target_min_voltage_V": voltage_min_pass,
                    "target_max_voltage_V": voltage_max_pass,
                    "trigger_voltage_V": float(voltage),
                    "current_to_target_A": float(current),
                    "current_to_target_mA": float(current * 1e3),
                    "avg_voltage_V": stats["avg_voltage"],
                    "min_voltage_V": stats["min_voltage"],
                    "max_voltage_V": stats["max_voltage"],
                    "sample_count": stats["sample_count"]
                }

        final_voltage = measure_voltage_once(session)

        return {
            "test": f"{direction} DIODE SWEEP",
            "input_pin": input_pin,
            "status": "FAIL",
            "reason": (
                f"Did not reach target window "
                f"{voltage_min_pass:.3f} V to {voltage_max_pass:.3f} V "
                f"within {abs(current_stop) * 1e3:.3f} mA"
            ),
            "target_min_voltage_V": voltage_min_pass,
            "target_max_voltage_V": voltage_max_pass,
            "final_voltage_V": float(final_voltage),
            "current_to_target_A": float(currents[-1]),
            "current_to_target_mA": float(currents[-1] * 1e3)
        }

    finally:
        disable_smu_output(session)


# ---------------- DIRECTION-SPECIFIC HELPERS ----------------

def run_forward_sweep(session, input_pin="IN+", **kwargs):
    """
    Run forward diode sweep.
    """
    return sweep_until_target(
        session=session,
        input_pin=input_pin,
        positive=True,
        **kwargs
    )


def run_reverse_sweep(session, input_pin="IN+", **kwargs):
    """
    Run reverse diode sweep.
    """
    return sweep_until_target(
        session=session,
        input_pin=input_pin,
        positive=False,
        **kwargs
    )


def run_full_diode_sweep_test(
    input_pin="IN+",
    smu_resource=SMU_RESOURCE,
    reset=True,
    current_switch_delay=CURRENT_SWITCH_DELAY,
    **kwargs
):
    """
    Open SMU session, run forward and reverse sweep, close session.
    Returns structured results for easy GUI use.
    """
    session = None
    results = {
        "forward_sweep": None,
        "reverse_sweep": None,
        "error": None
    }

    try:
        session = open_smu_session(resource_name=smu_resource, reset=reset)

        results["forward_sweep"] = run_forward_sweep(
            session=session,
            input_pin=input_pin,
            **kwargs
        )

        time.sleep(current_switch_delay)

        results["reverse_sweep"] = run_reverse_sweep(
            session=session,
            input_pin=input_pin,
            **kwargs
        )

    except Exception as e:
        results["error"] = str(e)

    finally:
        close_smu_session(session)

    return results


# ---------------- PRINT HELPERS ----------------

def print_sweep_result(result):
    """
    Pretty-print one sweep result.
    """
    if result is None:
        print("No result")
        return

    print(f"\n{result['test']}")
    print(f"  Input Pin: {result['input_pin']}")
    print(f"  Status: {result['status']}")

    if result["status"] == "PASS":
        print(f"  Trigger Voltage: {result['trigger_voltage_V']:.6f} V")
        print(f"  Current to Target: {result['current_to_target_mA']:.6f} mA")
        print(f"  Avg Voltage: {result['avg_voltage_V']:.6f} V")
        print(f"  Min Voltage: {result['min_voltage_V']:.6f} V")
        print(f"  Max Voltage: {result['max_voltage_V']:.6f} V")
        print(f"  Samples: {result['sample_count']}")
    else:
        print(f"  Reason: {result['reason']}")
        print(f"  Final Voltage: {result['final_voltage_V']:.6f} V")
        print(f"  Final Current: {result['current_to_target_mA']:.6f} mA")


def print_full_diode_sweep_results(results):
    """
    Pretty-print full test results.
    """
    if results.get("error"):
        print("\nTest Error:")
        print(results["error"])
        return

    print_sweep_result(results.get("forward_sweep"))
    print_sweep_result(results.get("reverse_sweep"))


# ---------------- MAIN ----------------

def main():
    input_pin = input("Enter input pin label (example IN+): ").strip() or "IN+"

    results = run_full_diode_sweep_test(input_pin=input_pin)
    print_full_diode_sweep_results(results)

    print("\nTest Complete")


if __name__ == "__main__":
    main()