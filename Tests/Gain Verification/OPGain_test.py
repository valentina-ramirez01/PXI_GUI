import time
import math
import numpy as np
import nidcpower
import nidmm


# ---------------- DEFAULT CONFIGURATION ----------------

SMU_RESOURCE = "SMU1"     # PXIe-4138 for VSRC1
PS_RESOURCE = "PXI4110"        # PXI-4110 from NI MAX
DMM_RESOURCE = "PXI4080"     # PXIe-4080

PS_POS_CHANNEL = "1"           # +15 V
PS_NEG_CHANNEL = "2"           # -15 V
9
POS_SUPPLY_V = 15.0
NEG_SUPPLY_V = -15.0
PS_CURRENT_LIMIT = 0.1

SMU_CURRENT_LIMIT = 1e-3

R1 = 1e3
R2 = 100e3

SAMPLE_COUNT = 30
MEASURE_DELAY = 0.1
SETTLE_DELAY = 2.0


# ---------------- SESSION HELPERS ----------------

def open_sessions():
    ps_session = nidcpower.Session(PS_RESOURCE)
    smu_session = nidcpower.Session(SMU_RESOURCE)
    dmm_session = nidmm.Session(DMM_RESOURCE)
    return ps_session, smu_session, dmm_session


def close_sessions(ps_session=None, smu_session=None, dmm_session=None):
    for session in [dmm_session, smu_session, ps_session]:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


# ---------------- PXI-4110 SUPPLY ----------------

def enable_supply(ps_session, channel_name, voltage, current_limit=PS_CURRENT_LIMIT):
    ch = ps_session.channels[channel_name]
    ch.voltage_level = float(voltage)
    ch.current_limit = float(current_limit)
    ch.output_enabled = True
    ch.output_connected = True
    return ch


def enable_dual_supply(ps_session, pos_v=POS_SUPPLY_V, neg_v=NEG_SUPPLY_V):
    pos_ch = enable_supply(ps_session, PS_POS_CHANNEL, pos_v)
    neg_ch = enable_supply(ps_session, PS_NEG_CHANNEL, neg_v)
    return pos_ch, neg_ch


def disable_dual_supply(ps_session):
    if ps_session is None:
        return

    for ch_name in [PS_POS_CHANNEL, PS_NEG_CHANNEL]:
        try:
            ch = ps_session.channels[ch_name]
            ch.voltage_level = 0.0
            time.sleep(0.2)
            ch.output_enabled = False
            ch.output_connected = False
        except Exception:
            pass


def read_supply(ch):
    return {
        "voltage_V": float(ch.measure(nidcpower.MeasurementTypes.VOLTAGE)),
        "current_A": float(ch.measure(nidcpower.MeasurementTypes.CURRENT))
    }


# ---------------- PXIe-4138 VSRC1 ----------------

def configure_smu_vsrc1(smu_session, voltage, current_limit=SMU_CURRENT_LIMIT):
    smu_session.source_mode = nidcpower.SourceMode.SINGLE_POINT
    smu_session.output_function = nidcpower.OutputFunction.DC_VOLTAGE
    smu_session.current_limit = float(current_limit)
    smu_session.voltage_level = float(voltage)
    smu_session.output_enabled = True


def set_vsrc1(smu_session, voltage):
    smu_session.voltage_level = float(voltage)


def measure_vsrc1(smu_session):
    with smu_session.initiate():
        v = smu_session.measure(nidcpower.MeasurementTypes.VOLTAGE)
    return float(v)


def disable_smu(smu_session):
    if smu_session is not None:
        try:
            smu_session.voltage_level = 0.0
            time.sleep(0.2)
            smu_session.output_enabled = False
        except Exception:
            pass


# ---------------- PXIe-4080 DMM ----------------

def configure_dmm(dmm_session):
    dmm_session.configure_measurement_digits(
        measurement_function=nidmm.Function.DC_VOLTS,
        range=10.0,
        resolution_digits=6.5
    )


def measure_dmm_average(dmm_session, sample_count=SAMPLE_COUNT, delay=MEASURE_DELAY):
    readings = []

    for _ in range(sample_count):
        time.sleep(delay)
        readings.append(float(dmm_session.read()))

    readings = np.array(readings)

    return {
        "avg_V": float(np.mean(readings)),
        "min_V": float(np.min(readings)),
        "max_V": float(np.max(readings)),
        "std_V": float(np.std(readings)),
        "samples": int(len(readings))
    }


# ---------------- GAIN CALCULATION ----------------

def calculate_open_loop_gain(vsrc1_1, vnull_1, vsrc1_2, vnull_2, r1=R1, r2=R2):
    delta_vsrc1 = vsrc1_2 - vsrc1_1
    delta_vnull = vnull_2 - vnull_1

    if abs(delta_vnull) < 1e-12:
        return {
            "gain_V_per_V": None,
            "gain_dB": None,
            "delta_vsrc1_V": delta_vsrc1,
            "delta_vnull_V": delta_vnull,
            "error": "Delta VNULL is too small"
        }

    scale_factor = (r1 + r2) / r1

    gain = -scale_factor * (delta_vsrc1 / delta_vnull)
    gain_db = 20.0 * math.log10(abs(gain))

    return {
        "gain_V_per_V": float(gain),
        "gain_dB": float(gain_db),
        "delta_vsrc1_V": float(delta_vsrc1),
        "delta_vnull_V": float(delta_vnull),
        "scale_factor": float(scale_factor),
        "error": None
    }


# ---------------- TEST CORE ----------------

def run_open_loop_gain_test(
    vsrc1_1,
    vsrc1_2,
    pos_supply=POS_SUPPLY_V,
    neg_supply=NEG_SUPPLY_V
):
    ps_session = None
    smu_session = None
    dmm_session = None

    results = {
        "power_up": None,
        "point_1": None,
        "point_2": None,
        "calculation": None,
        "error": None
    }

    try:
        ps_session, smu_session, dmm_session = open_sessions()

        configure_dmm(dmm_session)

        pos_ch, neg_ch = enable_dual_supply(
            ps_session,
            pos_v=pos_supply,
            neg_v=neg_supply
        )

        with ps_session.initiate():
            time.sleep(SETTLE_DELAY)

            results["power_up"] = {
                "positive_supply": read_supply(pos_ch),
                "negative_supply": read_supply(neg_ch)
            }

            configure_smu_vsrc1(smu_session, vsrc1_1)

            time.sleep(SETTLE_DELAY)

            vsrc1_meas_1 = measure_vsrc1(smu_session)
            vnull_stats_1 = measure_dmm_average(dmm_session)

            results["point_1"] = {
                "vsrc1_set_V": float(vsrc1_1),
                "vsrc1_measured_V": vsrc1_meas_1,
                "vnull_avg_V": vnull_stats_1["avg_V"],
                "vnull_min_V": vnull_stats_1["min_V"],
                "vnull_max_V": vnull_stats_1["max_V"],
                "vnull_std_V": vnull_stats_1["std_V"],
                "samples": vnull_stats_1["samples"]
            }

            set_vsrc1(smu_session, vsrc1_2)

            time.sleep(SETTLE_DELAY)

            vsrc1_meas_2 = measure_vsrc1(smu_session)
            vnull_stats_2 = measure_dmm_average(dmm_session)

            results["point_2"] = {
                "vsrc1_set_V": float(vsrc1_2),
                "vsrc1_measured_V": vsrc1_meas_2,
                "vnull_avg_V": vnull_stats_2["avg_V"],
                "vnull_min_V": vnull_stats_2["min_V"],
                "vnull_max_V": vnull_stats_2["max_V"],
                "vnull_std_V": vnull_stats_2["std_V"],
                "samples": vnull_stats_2["samples"]
            }

            results["calculation"] = calculate_open_loop_gain(
                vsrc1_1=vsrc1_meas_1,
                vnull_1=vnull_stats_1["avg_V"],
                vsrc1_2=vsrc1_meas_2,
                vnull_2=vnull_stats_2["avg_V"],
                r1=R1,
                r2=R2
            )

    except Exception as e:
        results["error"] = str(e)

    finally:
        disable_smu(smu_session)
        disable_dual_supply(ps_session)
        close_sessions(
            ps_session=ps_session,
            smu_session=smu_session,
            dmm_session=dmm_session
        )

    return results


# ---------------- PRINT HELPERS ----------------

def print_results(results):
    if results.get("error"):
        print("\nTEST ERROR")
        print(results["error"])
        return

    print("\nOPA551 Open-Loop Gain Test")
    print("Using professor nulling amplifier equation")
    print("\nEquation:")
    print("  GOL = -((R1 + R2) / R1) * (Delta VSRC1 / Delta VNULL)")
    print(f"\nR1 = {R1:.1f} ohms")
    print(f"R2 = {R2:.1f} ohms")
    print(f"Scale Factor = {(R1 + R2) / R1:.3f}")

    power = results.get("power_up")
    if power:
        print("\nPXI-4110 Power-Up Readback")
        print(f"  +Supply Voltage: {power['positive_supply']['voltage_V']:.6f} V")
        print(f"  +Supply Current: {power['positive_supply']['current_A']:.6f} A")
        print(f"  -Supply Voltage: {power['negative_supply']['voltage_V']:.6f} V")
        print(f"  -Supply Current: {power['negative_supply']['current_A']:.6f} A")

    p1 = results["point_1"]
    p2 = results["point_2"]

    print("\nPoint 1")
    print(f"  VSRC1 Set:      {p1['vsrc1_set_V']:.9f} V")
    print(f"  VSRC1 Measured: {p1['vsrc1_measured_V']:.9f} V")
    print(f"  VNULL Avg:      {p1['vnull_avg_V']:.9f} V")
    print(f"  VNULL Std:      {p1['vnull_std_V']:.9f} V")

    print("\nPoint 2")
    print(f"  VSRC1 Set:      {p2['vsrc1_set_V']:.9f} V")
    print(f"  VSRC1 Measured: {p2['vsrc1_measured_V']:.9f} V")
    print(f"  VNULL Avg:      {p2['vnull_avg_V']:.9f} V")
    print(f"  VNULL Std:      {p2['vnull_std_V']:.9f} V")

    calc = results["calculation"]

    print("\nCalculation")
    print(f"  Delta VSRC1: {calc['delta_vsrc1_V']:.9f} V")
    print(f"  Delta VNULL: {calc['delta_vnull_V']:.9f} V")

    if calc["error"]:
        print(f"  Error: {calc['error']}")
    else:
        print(f"  Open-Loop Gain: {calc['gain_V_per_V']:.3f} V/V")
        print(f"  Open-Loop Gain: {calc['gain_dB']:.2f} dB")


# ---------------- MAIN ----------------

def main():
    print("\nOPA551 Open-Loop Gain Automated Test")
    print("PXIe-4138 forces VSRC1")
    print("PXI-4110 provides +15 V and -15 V")
    print("PXIe-4080 measures VNULL / NE5532 output")

    pos_supply = float(input("\nEnter + supply voltage [15]: ").strip() or 15.0)
    neg_supply = float(input("Enter - supply voltage [-15]: ").strip() or -15.0)

    vsrc1_1 = float(input("Enter VSRC1 point 1 [0]: ").strip() or 0.0)
    vsrc1_2 = float(input("Enter VSRC1 point 2 [0.01]: ").strip() or 0.01)

    results = run_open_loop_gain_test(
        vsrc1_1=vsrc1_1,
        vsrc1_2=vsrc1_2,
        pos_supply=pos_supply,
        neg_supply=neg_supply
    )

    print_results(results)

    print("\nTest Complete")


if __name__ == "__main__":
    main()