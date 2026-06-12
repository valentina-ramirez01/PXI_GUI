import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import nifgen
import niscope
import nidcpower


class BandwidthGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("OPA551 Stepped Sine Bandwidth Test")
        self.root.geometry("1100x750")

        self.running = False
        self.freqs = None
        self.gain_db = None
        self.bw = None

        self.build_gui()

    def build_gui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        settings = ttk.LabelFrame(main, text="Test Settings", padding=10)
        settings.pack(fill="x")

        self.fgen_resource = tk.StringVar(value="Func_Gen")
        self.scope_resource = tk.StringVar(value="Scope")
        self.psu_resource = tk.StringVar(value="PXI4110")

        self.f_start = tk.DoubleVar(value=1e3)
        self.f_stop = tk.DoubleVar(value=10e6)
        self.n_points = tk.IntVar(value=50)

        self.n_avg = tk.IntVar(value=15)
        self.settle_time = tk.DoubleVar(value=0.1)

        self.amp = tk.DoubleVar(value=1.0)
        self.offset = tk.DoubleVar(value=0.0)

        self.sample_count = tk.IntVar(value=4096)
        self.scope_range = tk.DoubleVar(value=2.0)

        self.vpos = tk.DoubleVar(value=15.0)
        self.vneg = tk.DoubleVar(value=-15.0)
        self.current_limit = tk.DoubleVar(value=0.1)

        row = 0
        self.add_entry(settings, "FGEN Resource:", self.fgen_resource, row, 0)
        self.add_entry(settings, "Scope Resource:", self.scope_resource, row, 2)
        self.add_entry(settings, "PSU Resource:", self.psu_resource, row, 4)

        row += 1
        self.add_entry(settings, "Start Freq [Hz]:", self.f_start, row, 0)
        self.add_entry(settings, "Stop Freq [Hz]:", self.f_stop, row, 2)
        self.add_entry(settings, "Points:", self.n_points, row, 4)

        row += 1
        self.add_entry(settings, "Averages:", self.n_avg, row, 0)
        self.add_entry(settings, "Settle Time [s]:", self.settle_time, row, 2)

        row += 1
        self.add_entry(settings, "FGEN Amp:", self.amp, row, 0)
        self.add_entry(settings, "FGEN Offset:", self.offset, row, 2)

        row += 1
        self.add_entry(settings, "Samples:", self.sample_count, row, 0)
        self.add_entry(settings, "Scope Range [V]:", self.scope_range, row, 2)

        row += 1
        self.add_entry(settings, "+Supply [V]:", self.vpos, row, 0)
        self.add_entry(settings, "-Supply [V]:", self.vneg, row, 2)
        self.add_entry(settings, "Current Limit [A]:", self.current_limit, row, 4)

        note = ttk.Label(
            settings,
            text="Test uses CH0 only, averaged RMS magnitude, normalized to first frequency point.",
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
            columns=("freq", "gain_db"),
            show="headings",
            height=10
        )
        self.table.heading("freq", text="Frequency [Hz]")
        self.table.heading("gain_db", text="Normalized Gain [dB]")
        self.table.column("freq", width=200, anchor="center")
        self.table.column("gain_db", width=200, anchor="center")
        self.table.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scroll.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scroll.set)

        plot_frame = ttk.LabelFrame(main, text="Bandwidth Plot", padding=10)
        plot_frame.pack(fill="both", expand=True, pady=10)

        self.fig, self.ax = plt.subplots(figsize=(9, 4.5))
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.reset_plot()

    def add_entry(self, parent, label, variable, row, col):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="e", padx=5, pady=4)
        ttk.Entry(parent, textvariable=variable, width=16).grid(row=row, column=col + 1, sticky="w", padx=5, pady=4)

    def reset_plot(self):
        self.ax.clear()
        self.ax.set_title("Stepped Sine Bandwidth")
        self.ax.set_xlabel("Frequency [Hz]")
        self.ax.set_ylabel("Normalized Gain [dB]")
        self.ax.set_xscale("log")
        self.ax.grid(True, which="both")
        self.ax.axhline(-3, linestyle="--", label="-3 dB")
        self.ax.legend()
        self.canvas.draw()

    def clear_results(self):
        for item in self.table.get_children():
            self.table.delete(item)

        self.freqs = None
        self.gain_db = None
        self.bw = None

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
        psu = None
        fgen = None
        scope = None

        try:
            f_start = float(self.f_start.get())
            f_stop = float(self.f_stop.get())
            n_points = int(self.n_points.get())
            n_avg = int(self.n_avg.get())
            settle_time = float(self.settle_time.get())
            amp = float(self.amp.get())
            offset = float(self.offset.get())
            sample_count = int(self.sample_count.get())
            scope_range = float(self.scope_range.get())

            freqs = np.logspace(np.log10(f_start), np.log10(f_stop), n_points)

            self.update_status("Opening instruments...")

            psu = nidcpower.Session(self.psu_resource.get(), reset=True)
            fgen = nifgen.Session(self.fgen_resource.get())
            fgen.reset()
            scope = niscope.Session(self.scope_resource.get())
            scope.reset()

            self.update_status("Configuring supplies...")

            for ch_name, voltage in [("1", float(self.vpos.get())), ("2", float(self.vneg.get()))]:
                ch = psu.channels[ch_name]
                ch.output_function = nidcpower.OutputFunction.DC_VOLTAGE
                ch.voltage_level_range = 20.0
                ch.current_limit = float(self.current_limit.get())
                ch.voltage_level = voltage
                ch.output_enabled = True

            psu.initiate()

            self.update_status("Configuring function generator...")

            fgen.output_mode = nifgen.OutputMode.FUNC
            fgen.func_waveform = nifgen.Waveform.SINE
            fgen.func_amplitude = amp
            fgen.func_dc_offset = offset
            fgen.initiate()

            self.update_status("Configuring oscilloscope...")

            scope.configure_vertical(
                range=scope_range,
                coupling=niscope.VerticalCoupling.DC
            )

            scope.configure_trigger_immediate()

            gain = []

            print("Starting stepped sine sweep...")

            for f in freqs:
                self.update_status("Testing {:.3f} MHz...".format(f / 1e6))
                print("Testing {:.3f} MHz".format(f / 1e6))

                fgen.func_frequency = float(f)
                time.sleep(settle_time)

                rms_vals = []

                for _ in range(n_avg):
                    scope.abort()
                    scope.initiate()

                    waveform = scope.channels["0"].fetch(
                        num_samples=sample_count,
                        timeout=10.0
                    )[0]

                    data = np.array(waveform.samples)

                    mid = len(data) // 4
                    data = data[mid:-mid]

                    rms_vals.append(np.sqrt(np.mean(data ** 2)))

                v_rms = np.mean(rms_vals)
                gain.append(v_rms)

            gain = np.array(gain)
            gain_db = 20 * np.log10(gain / gain[0])

            idx = np.where(gain_db <= -3)[0]
            bw = freqs[idx[0]] if len(idx) else None

            self.freqs = freqs
            self.gain_db = gain_db
            self.bw = bw

            for f, gdb in zip(freqs, gain_db):
                self.root.after(0, self.add_row, f, gdb)

            self.root.after(0, self.update_plot)

            if bw is not None:
                result = "-3 dB Bandwidth ≈ {:.3f} MHz".format(bw / 1e6)
            else:
                result = "No -3 dB point found"

            self.root.after(0, lambda: self.result_label.config(text=result))
            self.update_status("Complete")

        except Exception as e:
            self.root.after(0, lambda err=e: messagebox.showerror("Test Error", str(err)))
            self.update_status("Error")

        finally:
            try:
                if fgen is not None:
                    fgen.abort()
                    fgen.close()
            except Exception:
                pass

            try:
                if psu is not None:
                    psu.close()
            except Exception:
                pass

            try:
                if scope is not None:
                    scope.close()
            except Exception:
                pass

            self.running = False
            self.root.after(0, lambda: self.start_button.config(state="normal"))

    def add_row(self, freq, gain_db):
        self.table.insert(
            "",
            "end",
            values=(
                "{:.3f}".format(freq),
                "{:.3f}".format(gain_db)
            )
        )

    def update_plot(self):
        self.ax.clear()
        self.ax.set_title("Stepped Sine Bandwidth")
        self.ax.set_xlabel("Frequency [Hz]")
        self.ax.set_ylabel("Normalized Gain [dB]")
        self.ax.set_xscale("log")
        self.ax.grid(True, which="both")

        self.ax.semilogx(self.freqs, self.gain_db, marker="o", label="Measured")
        self.ax.axhline(-3, linestyle="--", label="-3 dB")

        if self.bw is not None:
            self.ax.axvline(self.bw, linestyle="--", label="BW ≈ {:.3f} MHz".format(self.bw / 1e6))

        self.ax.legend()
        self.canvas.draw()


if __name__ == "__main__":
    root = tk.Tk()
    app = BandwidthGUI(root)
    root.mainloop()