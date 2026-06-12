#!/usr/bin/env python
# -- coding: utf-8 --

import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import nifgen
import niscope
import nidcpower
import numpy as np
import statistics

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


def calculate_slew_rate_from_capture(waveform_data, sample_rate, min_vpp=2.0):
    v_max = np.max(waveform_data)
    v_min = np.min(waveform_data)
    vpp = v_max - v_min

    if vpp < min_vpp:
        return None, None, None, None

    v_10 = v_min + 0.1 * vpp
    v_90 = v_min + 0.9 * vpp

    # Determine actual edge direction from beginning/end of capture
    start_avg = np.mean(waveform_data[:100])
    end_avg = np.mean(waveform_data[-100:])

    if end_avg > start_avg:
        edge_type = "Rising"
    else:
        edge_type = "Falling"

    indices = np.where((waveform_data > v_10) & (waveform_data < v_90))[0]

    if len(indices) <= 1:
        return None, v_10, v_90, edge_type

    dt = (indices[-1] - indices[0]) * (1.0 / sample_rate)

    if dt <= 0:
        return None, v_10, v_90, edge_type

    sr_v_us = ((v_90 - v_10) / dt) / 1e6
    return abs(sr_v_us), v_10, v_90, edge_type


def make_stats(data):
    data = np.array(data)

    if len(data) == 0:
        return {
            "samples": 0,
            "average": None,
            "median": None,
            "std_dev": None,
            "min": None,
            "max": None,
        }

    return {
        "samples": int(len(data)),
        "average": float(np.mean(data)),
        "median": float(statistics.median(data)),
        "std_dev": float(np.std(data)),
        "min": float(np.min(data)),
        "max": float(np.max(data)),
    }


def capture_until_both_edges(scope, chan, settings, update_callback=None):
    rising_results = []
    falling_results = []

    last_rising = {"t": None, "v": None, "v10": None, "v90": None}
    last_falling = {"t": None, "v": None, "v10": None, "v90": None}

    slopes = [
        niscope.TriggerSlope.POSITIVE,
        niscope.TriggerSlope.NEGATIVE
    ]

    slope_index = 0

    while len(rising_results) < settings["num_runs"] or len(falling_results) < settings["num_runs"]:
        try:
            scope.trigger_source = settings["scope_channel"]
            scope.trigger_level = settings["trigger_level"]
            scope.trigger_coupling = niscope.TriggerCoupling.DC
            scope.trigger_slope = slopes[slope_index]

            slope_index = 1 - slope_index

            waveform_info_list = chan.read(
                num_samples=settings["record_length"],
                timeout=settings["timeout"]
            )

            wfm = waveform_info_list[0]
            waveform_data = np.array(wfm.samples)
            t = wfm.relative_initial_x + np.arange(len(waveform_data)) * wfm.x_increment

            sr, v10, v90, edge_type = calculate_slew_rate_from_capture(
                waveform_data,
                settings["sample_rate"],
                settings["min_vpp"]
            )

            if sr is None:
                continue

            if edge_type == "Rising" and len(rising_results) < settings["num_runs"]:
                rising_results.append(sr)
                last_rising = {"t": t, "v": waveform_data, "v10": v10, "v90": v90}

                if update_callback is not None:
                    update_callback("Rising", len(rising_results), sr)

            elif edge_type == "Falling" and len(falling_results) < settings["num_runs"]:
                falling_results.append(sr)
                last_falling = {"t": t, "v": waveform_data, "v10": v10, "v90": v90}

                if update_callback is not None:
                    update_callback("Falling", len(falling_results), sr)

            time.sleep(0.05)

        except Exception:
            continue

    return rising_results, falling_results, last_rising, last_falling


def run_slew_rate_test(settings, update_callback=None):
    with nidcpower.Session(settings["ps_resource"], channels="1,2") as ps, \
            nifgen.Session(settings["fgen_resource"]) as fgen, \
            niscope.Session(settings["scope_resource"]) as scope:

        ps.channels[1].voltage_level = settings["positive_supply_v"]
        ps.channels[2].voltage_level = settings["negative_supply_v"]
        ps.channels["1,2"].output_enabled = True
        ps.initiate()

        try:
            fgen.output_mode = nifgen.OutputMode.FUNC
            fgen.configure_standard_waveform(
                waveform=nifgen.Waveform.SQUARE,
                amplitude=settings["amplitude_vpp"],
                frequency=settings["freq_hz"],
                dc_offset=settings["offset_v"]
            )
            fgen.initiate()

            chan = scope.channels[settings["scope_channel"]]
            chan.vertical_range = settings["scope_range_v"]
            chan.vertical_coupling = niscope.VerticalCoupling.DC

            scope.configure_horizontal_timing(
                settings["sample_rate"],
                settings["record_length"],
                50.0,
                1,
                True
            )

            rising, falling, last_rising, last_falling = capture_until_both_edges(
                scope,
                chan,
                settings,
                update_callback
            )

        finally:
            ps.channels["1,2"].output_enabled = False

    rising_stats = make_stats(rising)
    falling_stats = make_stats(falling)
    final_stats = make_stats(rising + falling)

    pass_limit = settings["pass_ratio"] * settings["expected_sr_v_us"]
    passed = final_stats["average"] is not None and final_stats["average"] >= pass_limit

    return {
        "chip_name": settings["chip_name"],
        "rising": rising_stats,
        "falling": falling_stats,
        "final": final_stats,
        "pass_limit": pass_limit,
        "expected": settings["expected_sr_v_us"],
        "pass": passed,
        "last_rising": last_rising,
        "last_falling": last_falling,
    }


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
            ("PXI-4110 Resource", "PXI4110"),
            ("PXIe-5413 Resource", "Func_Gen"),
            ("PXIe-5114 Resource", "Scope"),
            ("Scope Channel", "0"),

            ("Positive Supply V", "15.0"),
            ("Negative Supply V", "-15.0"),
            ("Frequency Hz", "10000"),
            ("Amplitude Vpp", "10.0"),
            ("Offset V", "0.0"),

            ("Expected SR V/us", "15.0"),
            ("Pass Ratio", "0.70"),
            ("Number of Runs", "30"),
            ("Sample Rate S/s", "100000000"),
            ("Record Length", "1000"),

            ("Scope Range V", "5.0"),
            ("Trigger Level V", "0.0"),
            ("Minimum Vpp", "2.0"),
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

        self.progress_label = tk.Label(
            control_frame,
            text="Runs: 0",
            font=("Arial", 10),
            width=45
        )
        self.progress_label.pack(side="left", padx=10)

        plot_frame = ttk.LabelFrame(self.root, text="Last Captured Rising and Falling Edges")
        plot_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.figure = Figure(figsize=(10, 4), dpi=100)
        self.ax_rise = self.figure.add_subplot(121)
        self.ax_fall = self.figure.add_subplot(122)

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        table_frame = ttk.LabelFrame(self.root, text="Results")
        table_frame.pack(fill="x", padx=10, pady=5)

        columns = ("Measurement", "Samples", "Average V/us", "Median V/us", "Std Dev", "Min", "Max")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", height=5)

        for col in columns:
            self.table.heading(col, text=col)
            self.table.column(col, width=135, anchor="center")

        self.table.pack(fill="x", padx=5, pady=5)

        self.result_label = tk.Label(
            self.root,
            text="Final Result: N/A",
            font=("Arial", 14, "bold"),
            bg="lightgray",
            width=55
        )
        self.result_label.pack(pady=8)

    def get_settings(self):
        return {
            "chip_name": self.entries["Chip Name"].get(),
            "ps_resource": self.entries["PXI-4110 Resource"].get(),
            "fgen_resource": self.entries["PXIe-5413 Resource"].get(),
            "scope_resource": self.entries["PXIe-5114 Resource"].get(),
            "scope_channel": self.entries["Scope Channel"].get(),

            "positive_supply_v": float(self.entries["Positive Supply V"].get()),
            "negative_supply_v": float(self.entries["Negative Supply V"].get()),
            "freq_hz": float(self.entries["Frequency Hz"].get()),
            "amplitude_vpp": float(self.entries["Amplitude Vpp"].get()),
            "offset_v": float(self.entries["Offset V"].get()),

            "expected_sr_v_us": float(self.entries["Expected SR V/us"].get()),
            "pass_ratio": float(self.entries["Pass Ratio"].get()),
            "num_runs": int(self.entries["Number of Runs"].get()),
            "sample_rate": float(self.entries["Sample Rate S/s"].get()),
            "record_length": int(self.entries["Record Length"].get()),

            "scope_range_v": float(self.entries["Scope Range V"].get()),
            "trigger_level": float(self.entries["Trigger Level V"].get()),
            "min_vpp": float(self.entries["Minimum Vpp"].get()),
            "timeout": 5.0,
        }

    def start_test(self):
        self.start_button.config(state="disabled")
        self.status_label.config(text="RUNNING", bg="yellow", fg="black")
        self.result_label.config(text="Final Result: Running...", bg="yellow", fg="black")
        self.progress_label.config(text="Runs: starting...")

        for item in self.table.get_children():
            self.table.delete(item)

        self.ax_rise.clear()
        self.ax_fall.clear()
        self.canvas.draw()

        thread = threading.Thread(target=self.run_test_thread)
        thread.daemon = True
        thread.start()

    def update_progress(self, edge_name, run_number, sr_value):
        self.root.after(
            0,
            lambda: self.progress_label.config(
                text="{} Runs: {} | Last: {:.2f} V/us".format(edge_name, run_number, sr_value)
            )
        )

    def run_test_thread(self):
        try:
            settings = self.get_settings()
            result = run_slew_rate_test(settings, update_callback=self.update_progress)
            self.root.after(0, lambda result=result: self.display_result(result))

        except Exception as e:
            error_message = str(e)
            self.root.after(0, lambda msg=error_message: self.display_error(msg))

    def display_error(self, error_message):
        self.start_button.config(state="normal")
        self.status_label.config(text="ERROR", bg="red", fg="white")
        self.result_label.config(text="Final Result: ERROR", bg="red", fg="white")
        messagebox.showerror("Test Error", error_message)

    def display_result(self, result):
        self.start_button.config(state="normal")

        avg = result["final"]["average"]

        if result["pass"]:
            self.status_label.config(text="PASS", bg="green", fg="white")
            self.result_label.config(
                text="Final Result: PASS | Final Slew Rate = {:.3f} V/us".format(avg),
                bg="green",
                fg="white"
            )
        else:
            self.status_label.config(text="FAIL", bg="red", fg="white")
            self.result_label.config(
                text="Final Result: FAIL | Final Slew Rate = {:.3f} V/us".format(avg),
                bg="red",
                fg="white"
            )

        self.update_table(result)
        self.update_plot(result)

    def update_table(self, result):
        for item in self.table.get_children():
            self.table.delete(item)

        def row(name, stats):
            return (
                name,
                stats["samples"],
                "{:.3f}".format(stats["average"]),
                "{:.3f}".format(stats["median"]),
                "{:.3f}".format(stats["std_dev"]),
                "{:.3f}".format(stats["min"]),
                "{:.3f}".format(stats["max"])
            )

        rows = [
            row("Rising slew rate", result["rising"]),
            row("Falling slew rate", result["falling"]),
            row("Final slew rate", result["final"]),
            ("Pass limit", "-", "{:.3f}".format(result["pass_limit"]), "-", "-", "-", "-"),
            ("Result", "-", "PASS" if result["pass"] else "FAIL", "-", "-", "Expected", "{:.3f} V/us".format(result["expected"])),
        ]

        for r in rows:
            self.table.insert("", "end", values=r)

    def plot_edge(self, ax, edge_data, title):
        ax.clear()

        t = edge_data["t"]
        v = edge_data["v"]
        v10 = edge_data["v10"]
        v90 = edge_data["v90"]

        if t is not None and v is not None:
            ax.plot(np.array(t) * 1e6, np.array(v))

            if v10 is not None:
                ax.axhline(v10, linestyle="--")

            if v90 is not None:
                ax.axhline(v90, linestyle="--")

            ax.set_ylim(-5.5, 5.5)

        ax.set_title(title)
        ax.set_xlabel("Time (us)")
        ax.set_ylabel("Vout (V)")
        ax.grid(True)

    def update_plot(self, result):
        self.plot_edge(
            self.ax_rise,
            result["last_rising"],
            "Last Rising Edge"
        )

        self.plot_edge(
            self.ax_fall,
            result["last_falling"],
            "Last Falling Edge"
        )

        self.figure.tight_layout()
        self.canvas.draw()


if __name__ == "__main__":
    root = tk.Tk()
    app = SlewRateGUI(root)
    root.mainloop()