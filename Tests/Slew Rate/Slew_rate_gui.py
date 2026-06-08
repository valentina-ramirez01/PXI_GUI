import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
import nifgen
import niscope

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


# ============================================================
# TEST FUNCTIONS
# ============================================================

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


def calculate_slew_rates(t, v, num_rising_edges, num_falling_edges):
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
        if len(rising_rates) >= num_rising_edges:
            break

        result = local_slew(idx, rising=True)

        if result is not None:
            sr, edge_data = result
            rising_rates.append(sr)
            rising_edge_data.append(edge_data)

    for idx in falling_edges_idx:
        if len(falling_rates) >= num_falling_edges:
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


def run_slew_rate_test(settings):
    with nifgen.Session(settings["fgen_resource"]) as fgen, niscope.Session(settings["scope_resource"]) as scope:

        fgen.output_mode = nifgen.OutputMode.FUNC

        fgen.configure_standard_waveform(
            waveform=nifgen.Waveform.SQUARE,
            amplitude=settings["amplitude_vpp"],
            frequency=settings["freq_hz"],
            dc_offset=settings["offset_v"],
            start_phase=0.0
        )

        scope.channels[settings["scope_channel"]].configure_vertical(
            range=settings["scope_range_v"],
            coupling=niscope.VerticalCoupling.DC,
            offset=0.0,
            probe_attenuation=1.0,
            enabled=True
        )

        scope.configure_horizontal_timing(
            min_sample_rate=settings["sample_rate"],
            min_num_pts=settings["record_length"],
            ref_position=10.0,
            num_records=1,
            enforce_realtime=True
        )

        scope.configure_trigger_edge(
            trigger_source=settings["scope_channel"],
            level=settings["trigger_level"],
            slope=niscope.TriggerSlope.POSITIVE,
            trigger_coupling=niscope.TriggerCoupling.DC
        )

        with fgen.initiate():
            time.sleep(0.5)

            with scope.initiate():
                waveforms = scope.channels[settings["scope_channel"]].fetch(
                    num_records=1,
                    timeout=settings["timeout"]
                )

        wfm = waveforms[0]
        v = np.array(wfm.samples)
        t = wfm.relative_initial_x + np.arange(len(v)) * wfm.x_increment

        results = calculate_slew_rates(
            t,
            v,
            settings["num_rising_edges"],
            settings["num_falling_edges"]
        )

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

        pass_limit = settings["pass_ratio"] * settings["expected_sr_v_per_us"]

        passed = (
            overall_stats["average"] is not None
            and overall_stats["average"] >= pass_limit
        )

        return {
            "chip_name": settings["chip_name"],
            "frequency_hz": settings["freq_hz"],
            "amplitude_vpp": settings["amplitude_vpp"],
            "offset_v": settings["offset_v"],
            "estimated_vlow": results["v_low"],
            "estimated_vhigh": results["v_high"],
            "rising": rising_stats,
            "falling": falling_stats,
            "overall": overall_stats,
            "expected_sr_v_per_us": settings["expected_sr_v_per_us"],
            "pass_limit_v_per_us": pass_limit,
            "pass": passed,
            "time": t,
            "voltage": v,
            "rising_edges": results["rising_edges"],
            "falling_edges": results["falling_edges"],
        }


# ============================================================
# GUI
# ============================================================

class SlewRateGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("OPA551 Slew Rate Test")
        self.root.geometry("1200x850")

        self.entries = {}

        self.build_gui()

    def build_gui(self):
        title = tk.Label(
            self.root,
            text="OPA551 Slew Rate Test",
            font=("Arial", 18, "bold")
        )
        title.pack(pady=8)

        settings_frame = ttk.LabelFrame(self.root, text="Test Settings")
        settings_frame.pack(fill="x", padx=10, pady=5)

        fields = [
            ("Chip Name", "OPA551"),
            ("PXIe-5413 Resource", "Func_Gen"),
            ("PXIe-5114 Resource", "Scope"),
            ("Scope Channel", "0"),
            ("Frequency Hz", "10000"),
            ("Amplitude Vpp", "8.0"),
            ("Offset V", "0.0"),
            ("Expected SR V/us", "15.0"),
            ("Pass Ratio", "0.70"),
            ("Rising Edges", "30"),
            ("Falling Edges", "30"),
            ("Sample Rate S/s", "100000000"),
            ("Record Length", "500000"),
            ("Scope Range V", "20.0"),
            ("Trigger Level V", "0.0"),
        ]

        for i, (label, default) in enumerate(fields):
            row = i // 3
            col = (i % 3) * 2

            ttk.Label(settings_frame, text=label + ":").grid(
                row=row, column=col, padx=5, pady=4, sticky="e"
            )

            entry = ttk.Entry(settings_frame, width=18)
            entry.insert(0, default)
            entry.grid(row=row, column=col + 1, padx=5, pady=4, sticky="w")

            self.entries[label] = entry

        control_frame = tk.Frame(self.root)
        control_frame.pack(fill="x", padx=10, pady=5)

        self.start_button = tk.Button(
            control_frame,
            text="Start Test",
            command=self.start_test,
            font=("Arial", 11, "bold"),
            width=15
        )
        self.start_button.pack(side="left", padx=5)

        self.status_label = tk.Label(
            control_frame,
            text="READY",
            bg="lightgray",
            font=("Arial", 12, "bold"),
            width=20
        )
        self.status_label.pack(side="left", padx=10)

        self.info_label = tk.Label(
            control_frame,
            text="Circuit: OPA551 buffer, OUT to IN−, RL = 3 kΩ to GND",
            font=("Arial", 10)
        )
        self.info_label.pack(side="left", padx=10)

        plot_frame = ttk.LabelFrame(self.root, text="Waveform and Edge Markers")
        plot_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.figure = Figure(figsize=(10, 4), dpi=100)
        self.ax = self.figure.add_subplot(111)

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        table_frame = ttk.LabelFrame(self.root, text="Results")
        table_frame.pack(fill="x", padx=10, pady=5)

        columns = ("Measurement", "Samples", "Average V/us", "Std Dev", "Min", "Max")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", height=5)

        for col in columns:
            self.table.heading(col, text=col)
            self.table.column(col, width=150, anchor="center")

        self.table.pack(fill="x", padx=5, pady=5)

        self.result_label = tk.Label(
            self.root,
            text="Final Result: N/A",
            font=("Arial", 14, "bold"),
            bg="lightgray",
            width=40
        )
        self.result_label.pack(pady=8)

    def get_settings(self):
        return {
            "chip_name": self.entries["Chip Name"].get(),
            "fgen_resource": self.entries["PXIe-5413 Resource"].get(),
            "scope_resource": self.entries["PXIe-5114 Resource"].get(),
            "scope_channel": self.entries["Scope Channel"].get(),
            "freq_hz": float(self.entries["Frequency Hz"].get()),
            "amplitude_vpp": float(self.entries["Amplitude Vpp"].get()),
            "offset_v": float(self.entries["Offset V"].get()),
            "expected_sr_v_per_us": float(self.entries["Expected SR V/us"].get()),
            "pass_ratio": float(self.entries["Pass Ratio"].get()),
            "num_rising_edges": int(self.entries["Rising Edges"].get()),
            "num_falling_edges": int(self.entries["Falling Edges"].get()),
            "sample_rate": float(self.entries["Sample Rate S/s"].get()),
            "record_length": int(self.entries["Record Length"].get()),
            "scope_range_v": float(self.entries["Scope Range V"].get()),
            "trigger_level": float(self.entries["Trigger Level V"].get()),
            "timeout": 10.0,
        }

    def start_test(self):
        self.start_button.config(state="disabled")
        self.status_label.config(text="RUNNING", bg="yellow")
        self.result_label.config(text="Final Result: Running...", bg="yellow")

        thread = threading.Thread(target=self.run_test_thread)
        thread.daemon = True
        thread.start()

    def run_test_thread(self):
        try:
            settings = self.get_settings()
            result = run_slew_rate_test(settings)

            self.root.after(0, lambda: self.display_result(result))

        except Exception as e:
            self.root.after(0, lambda: self.display_error(str(e)))

    def display_error(self, error_message):
        self.start_button.config(state="normal")
        self.status_label.config(text="ERROR", bg="red", fg="white")
        self.result_label.config(text="Final Result: ERROR", bg="red", fg="white")
        messagebox.showerror("Test Error", error_message)

    def display_result(self, result):
        self.start_button.config(state="normal")

        if result["pass"]:
            self.status_label.config(text="PASS", bg="green", fg="white")
            self.result_label.config(
                text="Final Result: PASS | Slew Rate = {:.3f} V/us".format(
                    result["overall"]["average"]
                ),
                bg="green",
                fg="white"
            )
        else:
            self.status_label.config(text="FAIL", bg="red", fg="white")
            avg = result["overall"]["average"]
            avg_text = "N/A" if avg is None else "{:.3f}".format(avg)
            self.result_label.config(
                text="Final Result: FAIL | Slew Rate = {} V/us".format(avg_text),
                bg="red",
                fg="white"
            )

        self.update_table(result)
        self.update_plot(result)

    def update_table(self, result):
        for item in self.table.get_children():
            self.table.delete(item)

        def fmt(value):
            if value is None:
                return "N/A"
            return "{:.3f}".format(value)

        rising = result["rising"]
        falling = result["falling"]
        overall = result["overall"]

        rows = [
            (
                "Rising slew rate",
                rising["samples"],
                fmt(rising["average"]),
                fmt(rising["std_dev"]),
                fmt(rising["min"]),
                fmt(rising["max"])
            ),
            (
                "Falling slew rate",
                falling["samples"],
                fmt(falling["average"]),
                fmt(falling["std_dev"]),
                fmt(falling["min"]),
                fmt(falling["max"])
            ),
            (
                "Final slew rate",
                overall["samples"],
                fmt(overall["average"]),
                fmt(overall["std_dev"]),
                fmt(overall["min"]),
                fmt(overall["max"])
            ),
            (
                "Pass limit",
                "-",
                "{:.3f}".format(result["pass_limit_v_per_us"]),
                "-",
                "-",
                "-"
            ),
            (
                "Result",
                "-",
                "PASS" if result["pass"] else "FAIL",
                "-",
                "Expected",
                "{:.3f} V/us".format(result["expected_sr_v_per_us"])
            ),
        ]

        for row in rows:
            self.table.insert("", "end", values=row)

    def update_plot(self, result):
        t_us = result["time"] * 1e6
        v = result["voltage"]

        self.ax.clear()
        self.ax.plot(t_us, v, label="Vout")

        if len(result["rising_edges"]) > 0:
            t10, t90, v10, v90 = result["rising_edges"][0]

            self.ax.axvline(t10 * 1e6, linestyle="--", label="Rising 10%")
            self.ax.axvline(t90 * 1e6, linestyle="--", label="Rising 90%")
            self.ax.axhline(v10, linestyle="--")
            self.ax.axhline(v90, linestyle="--")

        if len(result["falling_edges"]) > 0:
            t90, t10, v90, v10 = result["falling_edges"][0]

            self.ax.axvline(t90 * 1e6, linestyle=":", label="Falling 90%")
            self.ax.axvline(t10 * 1e6, linestyle=":", label="Falling 10%")

        self.ax.set_title("{} Slew Rate Capture".format(result["chip_name"]))
        self.ax.set_xlabel("Time (us)")
        self.ax.set_ylabel("Vout (V)")
        self.ax.grid(True)
        self.ax.legend()

        self.canvas.draw()


if __name__ == "__main__":
    root = tk.Tk()
    app = SlewRateGUI(root)
    root.mainloop()