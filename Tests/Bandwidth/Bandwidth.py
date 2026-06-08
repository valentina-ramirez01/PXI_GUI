# FULL FIXED CODE
# Main fix: use same/default small channel ranges first.
# CH0 = Vin, CH1 = Vout.
# Start with Vin Range = 0.5 V and Vout Range = 0.5 V for direct-channel verification.
# For real gain 10 test, change Vout Range to 2.0 V.

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import nifgen
import niscope


FGEN_RESOURCE_DEFAULT = "Func_Gen"
SCOPE_RESOURCE_DEFAULT = "Scope"

VIN_CHANNEL = "0"
VOUT_CHANNEL = "1"

RF = 10000.0
RG = 1100.0


def waveform_to_array(waveform):
    if hasattr(waveform, "samples"):
        return np.array(waveform.samples, dtype=float)

    if isinstance(waveform, list):
        data = []
        for item in waveform:
            if hasattr(item, "samples"):
                data.extend(item.samples)
            elif isinstance(item, (list, tuple, np.ndarray)):
                data.extend(item)
            else:
                data.append(item)
        return np.array(data, dtype=float)

    return np.array(waveform, dtype=float)


def robust_vpp(data):
    data = waveform_to_array(data)
    data = data[np.isfinite(data)]

    if len(data) < 20:
        return np.nan

    return np.percentile(data, 99.5) - np.percentile(data, 0.5)


def frequency_points():
    return np.array([
        100,
        200,
        500,
        1e3,
        2e3,
        5e3,
        10e3,
        20e3,
        50e3,
        100e3,
        200e3,
        300e3,
        350e3,
        400e3,
        450e3,
        500e3,
        700e3,
        1e6
    ], dtype=float)


def estimate_bandwidth(freqs, gains_db):
    freqs = np.array(freqs, dtype=float)
    gains_db = np.array(gains_db, dtype=float)

    valid = np.isfinite(freqs) & np.isfinite(gains_db)
    freqs = freqs[valid]
    gains_db = gains_db[valid]

    if len(freqs) < 5:
        return np.nan, np.nan, np.nan

    low_gain_db = np.mean(gains_db[:4])
    target_db = low_gain_db - 3.0

    for i in range(1, len(freqs)):
        if gains_db[i] <= target_db:
            f1, f2 = freqs[i - 1], freqs[i]
            g1, g2 = gains_db[i - 1], gains_db[i]

            logf1 = np.log10(f1)
            logf2 = np.log10(f2)

            if g2 == g1:
                bw = f2
            else:
                log_bw = logf1 + (target_db - g1) * (logf2 - logf1) / (g2 - g1)
                bw = 10 ** log_bw

            return bw, low_gain_db, target_db

    return np.nan, low_gain_db, target_db


class BandwidthGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("OPA551 Stepped Bandwidth Test")
        self.root.geometry("1200x800")

        self.running = False
        self.freqs = []
        self.gains_db = []

        self.build_gui()

    def build_gui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        settings = ttk.LabelFrame(main, text="Test Settings", padding=10)
        settings.pack(fill="x")

        self.chip_name = tk.StringVar(value="OPA551")
        self.fgen_resource = tk.StringVar(value=FGEN_RESOURCE_DEFAULT)
        self.scope_resource = tk.StringVar(value=SCOPE_RESOURCE_DEFAULT)

        self.amplitude = tk.DoubleVar(value=0.05)
        self.offset = tk.DoubleVar(value=0.0)

        self.vin_range = tk.DoubleVar(value=0.5)
        self.vout_range = tk.DoubleVar(value=0.5)

        self.cycles = tk.DoubleVar(value=10)
        self.max_sample_rate = tk.DoubleVar(value=50e6)

        row = 0
        self.add_entry(settings, "Chip Name:", self.chip_name, row, 0)
        self.add_entry(settings, "FGEN Resource:", self.fgen_resource, row, 2)
        self.add_entry(settings, "Scope Resource:", self.scope_resource, row, 4)

        row += 1
        self.add_entry(settings, "Amplitude [Vpeak]:", self.amplitude, row, 0)
        self.add_entry(settings, "Offset [V]:", self.offset, row, 2)

        row += 1
        self.add_entry(settings, "Scope Vin Range [V]:", self.vin_range, row, 0)
        self.add_entry(settings, "Scope Vout Range [V]:", self.vout_range, row, 2)

        row += 1
        self.add_entry(settings, "Cycles Captured:", self.cycles, row, 0)
        self.add_entry(settings, "Max Sample Rate [S/s]:", self.max_sample_rate, row, 2)

        note = ttk.Label(
            settings,
            text="Connections: 5413 OUT → IN+, 5114 CH0 → IN+, 5114 CH1 → OUT, RF=10kΩ, RG=1.1kΩ, supplies=±15V",
            foreground="blue"
        )
        note.grid(row=row + 1, column=0, columnspan=6, sticky="w", pady=8)

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=10)

        self.start_button = ttk.Button(buttons, text="Start Test", command=self.start_test)
        self.start_button.pack(side="left", padx=5)

        self.clear_button = ttk.Button(buttons, text="Clear", command=self.clear_results)
        self.clear_button.pack(side="left", padx=5)

        self.status_label = ttk.Label(buttons, text="Status: Ready")
        self.status_label.pack(side="left", padx=20)

        self.result_label = ttk.Label(main, text="Bandwidth: ---", font=("Arial", 14, "bold"))
        self.result_label.pack(fill="x", pady=5)

        table_frame = ttk.LabelFrame(main, text="Results", padding=10)
        table_frame.pack(fill="both", expand=True)

        self.table = ttk.Treeview(
            table_frame,
            columns=("freq", "vin", "vout", "gain", "gain_db"),
            show="headings",
            height=10
        )

        for col, title in {
            "freq": "Frequency [Hz]",
            "vin": "Vin [Vpp]",
            "vout": "Vout [Vpp]",
            "gain": "Gain [V/V]",
            "gain_db": "Gain [dB]"
        }.items():
            self.table.heading(col, text=title)
            self.table.column(col, anchor="center", width=150)

        self.table.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scroll.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scroll.set)

        plot_frame = ttk.LabelFrame(main, text="Frequency Response", padding=10)
        plot_frame.pack(fill="both", expand=True, pady=10)

        self.fig, self.ax = plt.subplots(figsize=(9, 4.5))
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.reset_plot()

    def add_entry(self, parent, label, variable, row, col):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="e", padx=5, pady=4)
        ttk.Entry(parent, textvariable=variable, width=18).grid(row=row, column=col + 1, sticky="w", padx=5, pady=4)

    def reset_plot(self):
        self.ax.clear()
        self.ax.set_title("OPA551 Closed-Loop Bandwidth Test")
        self.ax.set_xlabel("Frequency [Hz]")
        self.ax.set_ylabel("Gain [dB]")
        self.ax.set_xscale("log")
        self.ax.grid(True, which="both")
        self.canvas.draw()

    def clear_results(self):
        for item in self.table.get_children():
            self.table.delete(item)

        self.freqs = []
        self.gains_db = []

        self.result_label.config(text="Bandwidth: ---")
        self.status_label.config(text="Status: Ready")
        self.reset_plot()

    def start_test(self):
        if self.running:
            return

        self.clear_results()
        self.running = True
        self.start_button.config(state="disabled")

        thread = threading.Thread(target=self.run_test)
        thread.daemon = True
        thread.start()

    def update_status(self, text):
        self.root.after(0, lambda: self.status_label.config(text="Status: " + text))

    def run_test(self):
        fgen = None
        scope = None

        try:
            chip = self.chip_name.get()
            amp = float(self.amplitude.get())
            offset = float(self.offset.get())
            cycles = float(self.cycles.get())
            max_sr = float(self.max_sample_rate.get())

            expected_gain = 1 + RF / RG
            expected_gain_db = 20 * np.log10(expected_gain)

            freqs = frequency_points()

            self.update_status("Opening instruments...")

            fgen = nifgen.Session(self.fgen_resource.get())
            scope = niscope.Session(self.scope_resource.get())

            fgen.output_mode = nifgen.OutputMode.FUNC
            fgen.output_enabled = True

            scope.channels[VIN_CHANNEL].configure_vertical(
                range=float(self.vin_range.get()),
                coupling=niscope.VerticalCoupling.DC,
                probe_attenuation=1.0,
                enabled=True
            )

            scope.channels[VOUT_CHANNEL].configure_vertical(
                range=float(self.vout_range.get()),
                coupling=niscope.VerticalCoupling.DC,
                probe_attenuation=1.0,
                enabled=True
            )

            scope.configure_trigger_immediate()

            for freq in freqs:
                self.update_status("Testing {:.0f} Hz...".format(freq))

                fgen.abort()
                fgen.configure_standard_waveform(
                    waveform=nifgen.Waveform.SINE,
                    amplitude=amp,
                    dc_offset=offset,
                    frequency=float(freq),
                    start_phase=0.0
                )
                fgen.initiate()

                time.sleep(0.25)

                record_time = cycles / freq
                sample_rate = min(max_sr, max(200 * freq, 1e6))
                num_samples = int(sample_rate * record_time)

                if num_samples < 3000:
                    num_samples = 3000

                if num_samples > 500000:
                    num_samples = 500000

                scope.configure_horizontal_timing(
                    min_sample_rate=sample_rate,
                    min_num_pts=num_samples,
                    ref_position=50.0,
                    num_records=1,
                    enforce_realtime=False
                )

                scope.initiate()

                vin_waveform = scope.channels[VIN_CHANNEL].fetch(
                    num_samples=num_samples,
                    timeout=10.0
                )

                vout_waveform = scope.channels[VOUT_CHANNEL].fetch(
                    num_samples=num_samples,
                    timeout=10.0
                )

                vin = waveform_to_array(vin_waveform)
                vout = waveform_to_array(vout_waveform)

                vin_pp = robust_vpp(vin)
                vout_pp = robust_vpp(vout)

                gain = vout_pp / vin_pp if vin_pp > 0 else np.nan
                gain_db = 20 * np.log10(gain) if gain > 0 else np.nan

                self.freqs.append(freq)
                self.gains_db.append(gain_db)

                self.root.after(0, self.add_row, freq, vin_pp, vout_pp, gain, gain_db)
                self.root.after(0, self.update_plot)

                print(
                    "f={:.0f} Hz | Vin={:.6f} Vpp | Vout={:.6f} Vpp | Gain={:.4f} | Gain dB={:.2f}".format(
                        freq, vin_pp, vout_pp, gain, gain_db
                    )
                )

            bw, low_gain, target = estimate_bandwidth(self.freqs, self.gains_db)

            if np.isfinite(bw):
                result = (
                    "{} Bandwidth ≈ {:.2f} Hz | Low-Frequency Gain = {:.2f} dB | "
                    "-3 dB Target = {:.2f} dB | Expected = {:.2f} V/V ({:.2f} dB)"
                ).format(chip, bw, low_gain, target, expected_gain, expected_gain_db)
            else:
                result = (
                    "Bandwidth not reached | Low-Frequency Gain = {:.2f} dB | "
                    "-3 dB Target = {:.2f} dB | Expected = {:.2f} V/V ({:.2f} dB)"
                ).format(low_gain, target, expected_gain, expected_gain_db)

            self.root.after(0, lambda: self.result_label.config(text=result))
            self.update_status("Complete")

        except Exception as e:
            self.root.after(0, lambda err=e: messagebox.showerror("Test Error", str(err)))
            self.update_status("Error")

        finally:
            try:
                if fgen is not None:
                    fgen.abort()
                    fgen.output_enabled = False
                    fgen.close()
            except Exception:
                pass

            try:
                if scope is not None:
                    scope.close()
            except Exception:
                pass

            self.running = False
            self.root.after(0, lambda: self.start_button.config(state="normal"))

    def add_row(self, freq, vin_pp, vout_pp, gain, gain_db):
        self.table.insert(
            "",
            "end",
            values=(
                "{:.0f}".format(freq),
                "{:.6f}".format(vin_pp),
                "{:.6f}".format(vout_pp),
                "{:.4f}".format(gain),
                "{:.2f}".format(gain_db)
            )
        )

    def update_plot(self):
        self.ax.clear()
        self.ax.set_title("OPA551 Closed-Loop Bandwidth Test")
        self.ax.set_xlabel("Frequency [Hz]")
        self.ax.set_ylabel("Gain [dB]")
        self.ax.set_xscale("log")
        self.ax.grid(True, which="both")

        if len(self.freqs) > 0:
            self.ax.plot(self.freqs, self.gains_db, marker="o", label="Measured Gain")

        bw, low_gain, target = estimate_bandwidth(self.freqs, self.gains_db)

        if np.isfinite(low_gain):
            self.ax.axhline(low_gain, linestyle="--", label="Low-Frequency Gain")
            self.ax.axhline(target, linestyle="--", label="-3 dB Level")

        if np.isfinite(bw):
            self.ax.axvline(bw, linestyle="--", label="BW ≈ {:.2f} Hz".format(bw))

        self.ax.legend()
        self.canvas.draw()


if __name__ == "__main__":
    root = tk.Tk()
    app = BandwidthGUI(root)
    root.mainloop()