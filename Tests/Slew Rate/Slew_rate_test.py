import time
import numpy as np
import nifgen
import niscope

# ---------------- USER SETTINGS ----------------
FGEN_RESOURCE = "Func_Gen"
SCOPE_RESOURCE = "Scope"
SCOPE_CHANNEL = "0"

FREQ_HZ = 10_000
AMPLITUDE_VPP = 8.0
OFFSET_V = 0

NUM_RISING_EDGES = 30
NUM_FALLING_EDGES = 30

SCOPE_RANGE_V = 20.0
SCOPE_SAMPLE_RATE = 100e6
RECORD_LENGTH = 500000
TRIGGER_LEVEL = 0.0
TIMEOUT = 10.0

EXPECTED_SR_V_PER_US = 15.0
PASS_RATIO = 0.70
# ------------------------------------------------


def interpolate_crossing(t1, v1, t2, v2, v_target):
    if v2 == v1:
        return t1
    return t1 + (v_target - v1) * (t2 - t1) / (v2 - v1)


def find_crossing_time(t, v, start_idx, stop_idx, target, rising=True):
    for i in range(start_idx, stop_idx - 1):
        if rising:
            if v[i] <= target <= v[i + 1]:
                return interpolate_crossing(t[i], v[i], t[i + 1], v[i + 1], target)
        else:
            if v[i] >= target >= v[i + 1]:
                return interpolate_crossing(t[i], v[i], t[i + 1], v[i + 1], target)
    return None


def group_edges(indices, min_spacing=2000):
    edges = []
    last = -min_spacing

    for idx in indices:
        if idx - last > min_spacing:
            edges.append(idx)
            last = idx

    return edges


def calculate_slew_rates(t, v):
    rising_rates = []
    falling_rates = []
    rising_edge_data = []
    falling_edge_data = []

    dv = np.diff(v)
    dv_smooth = np.convolve(dv, np.ones(5) / 5.0, mode="same")

    rise_threshold = 0.5 * np.max(dv_smooth)
    fall_threshold = 0.5 * np.min(dv_smooth)

    rising_candidates = np.where(dv_smooth > rise_threshold)[0]
    falling_candidates = np.where(dv_smooth < fall_threshold)[0]

    rising_edges_idx = group_edges(rising_candidates)
    falling_edges_idx = group_edges(falling_candidates)

    # Skip first edge because trigger edge can be weird/incomplete
    if len(rising_edges_idx) > 1:
        rising_edges_idx = rising_edges_idx[1:]

    if len(falling_edges_idx) > 1:
        falling_edges_idx = falling_edges_idx[1:]

    def local_slew(edge_idx, rising=True):
        pre_start = max(0, edge_idx - 800)
        pre_stop = max(0, edge_idx - 200)

        post_start = min(len(v) - 1, edge_idx + 200)
        post_stop = min(len(v) - 1, edge_idx + 800)

        if pre_stop <= pre_start or post_stop <= post_start:
            return None

        v_before = np.mean(v[pre_start:pre_stop])
        v_after = np.mean(v[post_start:post_stop])

        if rising:
            v_low = v_before
            v_high = v_after
        else:
            v_high = v_before
            v_low = v_after

        v10 = v_low + 0.10 * (v_high - v_low)
        v90 = v_low + 0.90 * (v_high - v_low)

        search_start = max(0, edge_idx - 100)
        search_stop = min(len(v) - 1, edge_idx + 300)

        if rising:
            t10 = find_crossing_time(t, v, search_start, search_stop, v10, rising=True)
            t90 = find_crossing_time(t, v, search_start, search_stop, v90, rising=True)

            if t10 is None or t90 is None or t90 <= t10:
                return None

            sr = (v90 - v10) / (t90 - t10) / 1e6
            return sr, (t10, t90, v10, v90)

        else:
            t90 = find_crossing_time(t, v, search_start, search_stop, v90, rising=False)
            t10 = find_crossing_time(t, v, search_start, search_stop, v10, rising=False)

            if t10 is None or t90 is None or t10 <= t90:
                return None

            sr = abs((v10 - v90) / (t10 - t90) / 1e6)
            return sr, (t90, t10, v90, v10)

    for idx in rising_edges_idx:
        if len(rising_rates) >= NUM_RISING_EDGES:
            break

        result = local_slew(idx, rising=True)

        if result is not None:
            sr, edge_data = result
            rising_rates.append(sr)
            rising_edge_data.append(edge_data)

    for idx in falling_edges_idx:
        if len(falling_rates) >= NUM_FALLING_EDGES:
            break

        result = local_slew(idx, rising=False)

        if result is not None:
            sr, edge_data = result
            falling_rates.append(sr)
            falling_edge_data.append(edge_data)

    return {
        "v_low": float(np.percentile(v, 5)),
        "v_high": float(np.percentile(v, 95)),
        "rising_rates": np.array(rising_rates),
        "falling_rates": np.array(falling_rates),
        "rising_edges": rising_edge_data,
        "falling_edges": falling_edge_data,
    }


def make_stats(data):
    data = np.array(data)

    if len(data) == 0:
        return {
            "samples": 0,
            "average": None,
            "std_dev": None,
            "min": None,
            "max": None,
            "values": [],
        }

    return {
        "samples": int(len(data)),
        "average": float(np.mean(data)),
        "std_dev": float(np.std(data)),
        "min": float(np.min(data)),
        "max": float(np.max(data)),
        "values": [float(x) for x in data],
    }


def print_stats(name, stats):
    if stats["samples"] == 0:
        print("{}: No valid edges found".format(name))
        return

    print("\n{} Slew Rate".format(name))
    print("Samples: {}".format(stats["samples"]))
    print("Average: {:.3f} V/us".format(stats["average"]))
    print("Std Dev: {:.3f} V/us".format(stats["std_dev"]))
    print("Min:     {:.3f} V/us".format(stats["min"]))
    print("Max:     {:.3f} V/us".format(stats["max"]))

    print("Values:")
    for i, value in enumerate(stats["values"], start=1):
        print("  {:02d}: {:.3f} V/us".format(i, value))


def run_slew_rate_test(
    fgen_resource=FGEN_RESOURCE,
    scope_resource=SCOPE_RESOURCE,
    scope_channel=SCOPE_CHANNEL,
    freq_hz=FREQ_HZ,
    amplitude_vpp=AMPLITUDE_VPP,
    offset_v=OFFSET_V,
    scope_range_v=SCOPE_RANGE_V,
    sample_rate=SCOPE_SAMPLE_RATE,
    record_length=RECORD_LENGTH,
    trigger_level=TRIGGER_LEVEL,
    timeout=TIMEOUT,
    expected_sr_v_per_us=EXPECTED_SR_V_PER_US,
    pass_ratio=PASS_RATIO,
):
    with nifgen.Session(fgen_resource) as fgen, niscope.Session(scope_resource) as scope:

        # ---------------- PXIe-5413 CONFIG ----------------
        fgen.output_mode = nifgen.OutputMode.FUNC

        fgen.configure_standard_waveform(
            waveform=nifgen.Waveform.SQUARE,
            amplitude=amplitude_vpp,
            frequency=freq_hz,
            dc_offset=offset_v,
            start_phase=0.0
        )

        # ---------------- PXIe-5114 CONFIG ----------------
        scope.channels[scope_channel].configure_vertical(
            range=scope_range_v,
            coupling=niscope.VerticalCoupling.DC,
            offset=0.0,
            probe_attenuation=1.0,
            enabled=True
        )

        scope.configure_horizontal_timing(
            min_sample_rate=sample_rate,
            min_num_pts=record_length,
            ref_position=10.0,
            num_records=1,
            enforce_realtime=True
        )

        scope.configure_trigger_edge(
            trigger_source=scope_channel,
            level=trigger_level,
            slope=niscope.TriggerSlope.POSITIVE,
            trigger_coupling=niscope.TriggerCoupling.DC
        )

        with fgen.initiate():
            time.sleep(0.5)

            with scope.initiate():
                waveforms = scope.channels[scope_channel].fetch(
                    num_records=1,
                    timeout=timeout
                )

        wfm = waveforms[0]
        v = np.array(wfm.samples)
        t = wfm.relative_initial_x + np.arange(len(v)) * wfm.x_increment

        results = calculate_slew_rates(t, v)

        rising = results["rising_rates"]
        falling = results["falling_rates"]

        rising_stats = make_stats(rising)
        falling_stats = make_stats(falling)

        if len(rising) > 0 and len(falling) > 0:
            all_rates = np.concatenate((rising, falling))
        elif len(rising) > 0:
            all_rates = rising
        elif len(falling) > 0:
            all_rates = falling
        else:
            all_rates = np.array([])

        overall_stats = make_stats(all_rates)

        if overall_stats["average"] is not None:
            limit = pass_ratio * expected_sr_v_per_us
            passed = overall_stats["average"] >= limit
        else:
            limit = pass_ratio * expected_sr_v_per_us
            passed = False

        return {
            "test_name": "OPA551 Slew Rate",
            "input_waveform": "square",
            "frequency_hz": float(freq_hz),
            "amplitude_vpp": float(amplitude_vpp),
            "offset_v": float(offset_v),
            "scope_sample_rate": float(sample_rate),
            "record_length": int(record_length),
            "estimated_vlow": results["v_low"],
            "estimated_vhigh": results["v_high"],
            "rising": rising_stats,
            "falling": falling_stats,
            "overall": overall_stats,
            "expected_sr_v_per_us": float(expected_sr_v_per_us),
            "pass_limit_v_per_us": float(limit),
            "pass": bool(passed),
        }


def main():
    print("Starting OPA551 slew rate test...")

    result = run_slew_rate_test()

    print("\n========== OPA551 SLEW RATE RESULTS ==========")
    print("Input waveform: {:.1f} Vpp square wave at {:.1f} Hz".format(
        result["amplitude_vpp"],
        result["frequency_hz"]
    ))
    print("FGEN offset:     {:.3f} V".format(result["offset_v"]))
    print("Estimated Vlow:  {:.6f} V".format(result["estimated_vlow"]))
    print("Estimated Vhigh: {:.6f} V".format(result["estimated_vhigh"]))

    print_stats("Rising Edge", result["rising"])
    print_stats("Falling Edge", result["falling"])

    if result["overall"]["average"] is not None:
        print("\nOverall Average Slew Rate: {:.3f} V/us".format(
            result["overall"]["average"]
        ))
        print("Pass Limit: {:.3f} V/us".format(result["pass_limit_v_per_us"]))

        if result["pass"]:
            print("Status: PASS")
        else:
            print("Status: FAIL / CHECK SETUP")
    else:
        print("\nStatus: FAIL / no valid edges detected")


if __name__ == "__main__":
    main()