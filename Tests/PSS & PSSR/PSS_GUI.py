import tkinter as tk
from tkinter import ttk, messagebox
import threading
import math

import matplotlib
matplotlib.use("TkAgg")

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from PSS_Test import run_pss_test
from Close_Loop_Gain_PSSR import run_closed_loop_gain   


class PSS_GUI:

    def __init__(self, root):
        self.root = root
        self.root.title("Power Supply Sensitivity + PSRR Test")
        self.root.geometry("1300x900")

        # ---------------- LEFT PANEL ----------------
        left = ttk.Frame(root, padding=10)
        left.pack(side="left", fill="y")

        ttk.Label(left, text="PSS + PSRR TEST", font=("Arial", 16, "bold")).pack()

        # ---------------- SMU / DMM / PSU ----------------
        self.smu_neg = ttk.Entry(left)
        self.smu_neg.insert(0, "SMU1")
        ttk.Label(left, text="SMU Negative").pack()
        self.smu_neg.pack()

        self.smu_pos = ttk.Entry(left)
        self.smu_pos.insert(0, "SMU2")
        ttk.Label(left, text="SMU Positive").pack()
        self.smu_pos.pack()

        self.dmm = ttk.Entry(left)
        self.dmm.insert(0, "Multimeter")
        ttk.Label(left, text="DMM").pack()
        self.dmm.pack()

        self.psu = ttk.Entry(left)
        self.psu.insert(0, "PSU")
        ttk.Label(left, text="PSU").pack()
        self.psu.pack()

        self.psu_channel = ttk.Entry(left)
        self.psu_channel.insert(0, "0")
        ttk.Label(left, text="PSU Channel").pack()
        self.psu_channel.pack()

        # ---------------- PSS SETTINGS ----------------
        self.samples = ttk.Entry(left)
        self.samples.insert(0, "30")
        ttk.Label(left, text="Samples").pack()
        self.samples.pack()

        self.delay = ttk.Entry(left)
        self.delay.insert(0, "0.001")
        ttk.Label(left, text="Sample Delay").pack()
        self.delay.pack()

        self.start_v = ttk.Entry(left)
        self.start_v.insert(0, "5")
        ttk.Label(left, text="Start V").pack()
        self.start_v.pack()

        self.stop_v = ttk.Entry(left)
        self.stop_v.insert(0, "10")
        ttk.Label(left, text="Stop V").pack()
        self.stop_v.pack()

        self.step_v = ttk.Entry(left)
        self.step_v.insert(0, "1")
        ttk.Label(left, text="Step V").pack()
        self.step_v.pack()

        # ---------------- CLOSED LOOP GAIN INPUT ----------------
        ttk.Label(left, text="--- Closed Loop Gain Setup ---", font=("Arial", 11, "bold")).pack(pady=5)

        self.vin0 = ttk.Entry(left)
        self.vin0.insert(0, "0.0")
        ttk.Label(left, text="VIN0 (V)").pack()
        self.vin0.pack()

        self.vin1 = ttk.Entry(left)
        self.vin1.insert(0, "1.0")
        ttk.Label(left, text="VIN1 (V)").pack()
        self.vin1.pack()

        # ---------------- PASS CRITERIA ----------------
        ttk.Label(left, text="--- PASS CRITERIA ---", font=("Arial", 11, "bold")).pack(pady=5)
        self.max_psrr_uv = ttk.Entry(left)
        self.max_psrr_uv.insert(0, "30") 
        ttk.Label(left, text="Max PSRR (uV/V)").pack()
        self.max_psrr_uv.pack()

        # ---------------- BUTTON ----------------
        self.btn = ttk.Button(left, text="RUN TEST", command=self.start)
        self.btn.pack(pady=10)

        self.result = ttk.Label(left, text="READY", font=("Arial", 12, "bold"))
        self.result.pack(pady=5)

        # ---------------- RESULTS ----------------
        self.pass_label = ttk.Label(left, text="STATUS: ---", font=("Arial", 12, "bold"))
        self.pass_label.pack(pady=10)

        self.pss_label = ttk.Label(left, text="PSS: --- uV/V")
        self.pss_label.pack()

        self.db_label = ttk.Label(left, text="PSS: --- dB")
        self.db_label.pack()

        self.gain_label = ttk.Label(left, text="Gain: --- V/V")
        self.gain_label.pack()

        self.psrr_label = ttk.Label(left, text="PSRR: ---")
        self.psrr_label.pack()

        self.psrr_db_label = ttk.Label(left, text="PSRR dB: ---")
        self.psrr_db_label.pack()

        # ---------------- PLOT ----------------
        right = ttk.Frame(root)
        right.pack(side="right", fill="both", expand=True)

        self.fig = Figure(figsize=(7, 5))
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("PSS Result")
        self.ax.set_xlabel("Supply (V)")
        self.ax.set_ylabel("Vout (V)")
        self.ax.grid()

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    # ==========================================================
    # START THREAD
    # ==========================================================
    def start(self):
        self.btn.config(state="disabled")
        self.result.config(text="RUNNING")

        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        try:
            # ---------------- CLOSED LOOP GAIN ----------------
            gain = run_closed_loop_gain(
                self.psu.get(),
                self.smu_neg.get(),
                self.smu_pos.get(),
                self.dmm.get(),
                self.psu_channel.get(),   # <<< ADD THIS
                float(self.vin0.get()),
                float(self.vin1.get()),
                sample_count=int(self.samples.get())
            )

            # ---------------- PSS TEST ----------------
            r = run_pss_test(
                smu_neg_resource=self.smu_neg.get(),
                smu_pos_resource=self.smu_pos.get(),
                dmm_resource=self.dmm.get(),
                psu_resource=self.psu.get(),   # <<< ADD THIS
                sample_count=int(self.samples.get()),
                sample_delay=float(self.delay.get()),
                voltage_start=float(self.start_v.get()),
                voltage_stop=float(self.stop_v.get()),
                voltage_step=float(self.step_v.get()),
            )
            r["gain"] = gain

            self.root.after(0, lambda: self.update(r))

        except Exception as e:
            self.root.after(0, lambda: self.fail(str(e)))

    # ==========================================================
    # UPDATE UI
    # ==========================================================
    def update(self, r):

        gain = r["gain"]

        # ---------------- PSRR ----------------
        psrr_uv_per_v = r["pss_uv_per_v"] / gain if gain != 0 else float("inf")

        psrr_db = 20 * math.log10(psrr_uv_per_v / 1e6) if psrr_uv_per_v > 0 else float("-inf")

        # ---------------- PASS CRITERIA ----------------
        max_psrr = float(self.max_psrr_uv.get())

        psrr_ok = psrr_uv_per_v <= max_psrr

        if psrr_ok:
            status = "PASS"
            color = "green"
        else:
            status = "FAIL"
            color = "red"

        # ---------------- UI UPDATE ----------------
        self.pass_label.config(
            text=f"STATUS: {status}",
            foreground=color
        )

        self.result.config(
            text="PSS = {:.3f} uV/V | {:.2f} dB\nPSRR = {:.3f} uV/V | {:.2f} dB".format(
                r["pss_uv_per_v"],
                r["pss_db"],
                psrr_uv_per_v,   # make sure this exists in your update()
                psrr_db
            )
        )

        self.pss_label.config(
            text="PSS: {:.6f} uV/V".format(r["pss_uv_per_v"])
        )

        self.db_label.config(
            text="PSS: {:.3f} dB".format(r["pss_db"])
        )

        self.gain_label.config(
            text="Gain: {:.6f} V/V".format(gain)
        )

        self.psrr_label.config(
            text="PSRR: {:.6f} uV/V".format(psrr_uv_per_v)
        )

        self.psrr_db_label.config(
            text="PSRR dB: {:.3f}".format(psrr_db)
        )

        # ---------------- PLOT ----------------
        self.ax.clear()
        self.ax.grid()
        self.ax.set_title("Power Supply Sensitivity")
        self.ax.set_xlabel("Supply (V)")
        self.ax.set_ylabel("Vout (V)")

        self.ax.errorbar(
            r["supply"],
            r["vout_avg"],
            yerr=r["vout_std"],
            fmt="o-",
            label="Measured"
        )

        fit = [r["slope"] * x + r["intercept"] for x in r["supply"]]
        self.ax.plot(r["supply"], fit, "--", label="Fit")

        self.ax.legend()
        self.canvas.draw()

        self.btn.config(state="normal")
        
    # ==========================================================
    # ERROR
    # ==========================================================
    def fail(self, msg):
        messagebox.showerror("Error", msg)
        self.result.config(text="FAIL")
        self.btn.config(state="normal")


if __name__ == "__main__":
    root = tk.Tk()
    app = PSS_GUI(root)
    root.mainloop()

