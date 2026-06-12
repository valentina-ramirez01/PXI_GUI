import time
import math
import numpy as np
import nidcpower
import nidmm


# ---------------- DEFAULT CONFIGURATION ----------------

SMU_RESOURCE = "SMU1"          # PXIe-4138 for common-mode input
PS_RESOURCE = "PXI4110"       # PXI-4110
DMM_RESOURCE = "PXI4080"      # PXIe-4080

PS_POS_CHANNEL = "1"          # +15 V
PS_NEG_CHANNEL = "2"          # -15 V

POS_SUPPLY_V = 15.0
NEG_SUPPLY_V = -15.0

PS_CURRENT_LIMIT = 0.1
SMU_CURRENT_LIMIT = 1e-3

VCM_1 = 0.0
VCM_2 = 1.0

SAMPLE_COUNT = 30
MEASURE_DELAY = 0.1
SETTLE_DELAY = 5.0


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


# ---------------- PXI-4110 POWER SUPPLY ----------------

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


# ---------------- PXIe-4138 COMMON-MODE SOURCE ----------------

def configure_smu_voltage(smu_session, voltage, current_limit=SMU_CURRENT_LIMIT):
    smu_session.source_mode = nidcpower.SourceMode.SINGLE_POINT
    smu_session.output_function = nidcpower.OutputFunction.DC_VOLTAGE
    smu_session.current_limit = float(current_limit)
    smu_session.voltage_level = float(voltage)
    smu_session.output_enabled = True
    time.sleep(1.0)


def set_common_mode_voltage(smu_session, voltage):
    smu_session.voltage_level = float(voltage)
    time.sleep(1.0)


def measure_smu_voltage(smu_session):
    time.sleep(0.5)
    try:
        with smu_session.initiate():
            time.sleep(0.5)
            return float(smu_session.measure(nidcpower.MeasurementTypes.VOLTAGE))
    except Exception:
        return float(smu_session.voltage_level)

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

    readings = np.array(readings, dtype=float)

    return {
        "avg_V": float(np.mean(readings)),
        "min_V": float(np.min(readings)),
        "max_V": float(np.max(readings)),
        "std_V": float(np.std(readings)),
        "samples": int(len(readings))
    }


# ---------------- CALCULATION ----------------

def calculate_common_mode_gain(vcm1, vout1, vcm2, vout2):
    delta_vcm = vcm2 - vcm1
    delta_vout = vout2 - vout1

    if abs(delta_vcm) < 1e-12:
        return {
            "acm_V_per_V": None,
            "acm_dB": None,
            "delta_vcm_V": delta_vcm,
            "delta_vout_V": delta_vout,
            "error": "Delta VCM is too small"
        }

    acm = delta_vout / delta_vcm
    acm_db = 20.0 * math.log10(abs(acm)) if acm != 0 else -999.0

    return {
        "acm_V_per_V": float(acm),
        "acm_abs_V_per_V": float(abs(acm)),
        "acm_dB": float(acm_db),
        "delta_vcm_V": float(delta_vcm),
        "delta_vout_V": float(delta_vout),
        "error": None
    }


# ---------------- TEST CORE ----------------

def run_cmrr_common_mode_test(
    vcm1=VCM_1,
    vcm2=VCM_2,
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

            configure_smu_voltage(smu_session, vcm1)
            time.sleep(SETTLE_DELAY)

            vcm1_measured = measure_smu_voltage(smu_session)
            vout1_stats = measure_dmm_average(dmm_session)

            results["point_1"] = {
                "vcm_set_V": float(vcm1),
                "vcm_measured_V": vcm1_measured,
                "vout_avg_V": vout1_stats["avg_V"],
                "vout_min_V": vout1_stats["min_V"],
                "vout_max_V": vout1_stats["max_V"],
                "vout_std_V": vout1_stats["std_V"],
                "samples": vout1_stats["samples"]
            }

            set_common_mode_voltage(smu_session, vcm2)
            time.sleep(SETTLE_DELAY)

            vcm2_measured = measure_smu_voltage(smu_session)
            vout2_stats = measure_dmm_average(dmm_session)

            results["point_2"] = {
                "vcm_set_V": float(vcm2),
                "vcm_measured_V": vcm2_measured,
                "vout_avg_V": vout2_stats["avg_V"],
                "vout_min_V": vout2_stats["min_V"],
                "vout_max_V": vout2_stats["max_V"],
                "vout_std_V": vout2_stats["std_V"],
                "samples": vout2_stats["samples"]
            }

            results["calculation"] = calculate_common_mode_gain(
                vcm1=vcm1_measured,
                vout1=vout1_stats["avg_V"],
                vcm2=vcm2_measured,
                vout2=vout2_stats["avg_V"]
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

    print("\nOPA551 Common-Mode Gain / CMRR Test")
    print("Acm = Delta VOUT / Delta VCM")

    power = results.get("power_up")
    if power:
        print("\nPXI-4110 Power-Up Readback")
        print(f"  +Supply Voltage: {power['positive_supply']['voltage_V']:.6f} V")
        print(f"  +Supply Current: {power['positive_supply']['current_A']:.6f} A")
        print(f"  -Supply Voltage: {power['negative_supply']['voltage_V']:.6f} V")
        print(f"  -Supply Current: {power['negative_supply']['current_A']:.6f} A")

    p1 = results["point_1"]
    p2 = results["point_2"]
    calc = results["calculation"]

    print("\nPoint 1")
    print(f"  VCM Set:      {p1['vcm_set_V']:.9f} V")
    print(f"  VCM Measured: {p1['vcm_measured_V']:.9f} V")
    print(f"  VOUT Avg:     {p1['vout_avg_V']:.9f} V")
    print(f"  VOUT Std:     {p1['vout_std_V']:.9f} V")

    print("\nPoint 2")
    print(f"  VCM Set:      {p2['vcm_set_V']:.9f} V")
    print(f"  VCM Measured: {p2['vcm_measured_V']:.9f} V")
    print(f"  VOUT Avg:     {p2['vout_avg_V']:.9f} V")
    print(f"  VOUT Std:     {p2['vout_std_V']:.9f} V")

    print("\nCalculation")
    print(f"  Delta VCM:  {calc['delta_vcm_V']:.9f} V")
    print(f"  Delta VOUT: {calc['delta_vout_V']:.9f} V")

    if calc["error"]:
        print(f"  Error: {calc['error']}")
    else:
        print(f"  Common-Mode Gain: {calc['acm_V_per_V']:.9e} V/V")
        print(f"  Common-Mode Gain: {calc['acm_dB']:.2f} dB")


def main():
    print("\nOPA551 Common-Mode Gain Test")
    print("PXIe-4138 drives both inputs with same VCM")
    print("PXI-4110 provides supplies")
    print("PXIe-4080 measures output/null voltage")

    pos_supply = float(input("\nEnter + supply voltage [15]: ").strip() or 15.0)
    neg_supply = float(input("Enter - supply voltage [-15]: ").strip() or -15.0)

    vcm1 = float(input("Enter VCM point 1 [0]: ").strip() or 0.0)
    vcm2 = float(input("Enter VCM point 2 [1]: ").strip() or 1.0)

    results = run_cmrr_common_mode_test(
        vcm1=vcm1,
        vcm2=vcm2,
        pos_supply=pos_supply,
        neg_supply=neg_supply
    )

    print_results(results)
    print("\nTest Complete")


if __name__ == "__main__":
    main()