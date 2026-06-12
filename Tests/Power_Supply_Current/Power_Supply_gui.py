import tkinter as tk
from tkinter import ttk, messagebox
import threading

from power_supply_test import run_power_supply_current_test


class QuiescentCurrentGUI:

    def __init__(self, root):

        self.root = root
        self.root.title("Quiescent Current Test")
        self.root.geometry("1000x600")

        # ======================================================
        # MAIN LAYOUT
        # ======================================================

        left = ttk.Frame(root, padding=10)
        left.pack(side="left", fill="y")

        right = ttk.Frame(root, padding=10)
        right.pack(side="right", fill="both", expand=True)

        # ======================================================
        # LEFT PANEL
        # ======================================================

        ttk.Label(
            left,
            text="QUIESCENT CURRENT TEST",
            font=("Arial", 16, "bold")
        ).pack(pady=10)

        # ---------------- RESOURCES ----------------

        resource_frame = ttk.LabelFrame(
            left,
            text="Instrument Resources",
            padding=10
        )
        resource_frame.pack(fill="x", pady=5)

        ttk.Label(resource_frame, text="SMU1 Resource").pack(anchor="w")
        self.smu1 = ttk.Entry(resource_frame)
        self.smu1.insert(0, "SMU1")
        self.smu1.pack(fill="x", pady=2)

        ttk.Label(resource_frame, text="SMU2 Resource").pack(anchor="w")
        self.smu2 = ttk.Entry(resource_frame)
        self.smu2.insert(0, "SMU2")
        self.smu2.pack(fill="x", pady=2)

        # ---------------- TEST SETTINGS ----------------

        settings_frame = ttk.LabelFrame(
            left,
            text="Test Settings",
            padding=10
        )
        settings_frame.pack(fill="x", pady=5)

        ttk.Label(settings_frame, text="Supply Voltage (V)").pack(anchor="w")
        self.voltage = ttk.Entry(settings_frame)
        self.voltage.insert(0, "5")
        self.voltage.pack(fill="x", pady=2)

        ttk.Label(settings_frame, text="Max Quiescent Current (mA)").pack(anchor="w")
        self.max_iq = ttk.Entry(settings_frame)
        self.max_iq.insert(0, "8.5")
        self.max_iq.pack(fill="x", pady=2)

        ttk.Label(settings_frame, text="Current Limit (mA)").pack(anchor="w")
        self.current_limit = ttk.Entry(settings_frame)
        self.current_limit.insert(0, "50")
        self.current_limit.pack(fill="x", pady=2)

        ttk.Label(settings_frame, text="Sample Count").pack(anchor="w")
        self.sample_count = ttk.Entry(settings_frame)
        self.sample_count.insert(0, "30")
        self.sample_count.pack(fill="x", pady=2)

        ttk.Label(settings_frame, text="Sample Delay (s)").pack(anchor="w")
        self.sample_delay = ttk.Entry(settings_frame)
        self.sample_delay.insert(0, "0.01")
        self.sample_delay.pack(fill="x", pady=2)

        # ---------------- RUN BUTTON ----------------

        self.run_button = ttk.Button(
            left,
            text="RUN TEST",
            command=self.start_test
        )
        self.run_button.pack(fill="x", pady=15)

        self.status_label = ttk.Label(
            left,
            text="READY",
            font=("Arial", 14, "bold")
        )
        self.status_label.pack()

        # ======================================================
        # RIGHT PANEL
        # ======================================================

        ttk.Label(
            right,
            text="TEST RESULTS",
            font=("Arial", 18, "bold")
        ).pack(pady=10)

        self.overall_result = ttk.Label(
            right,
            text="OVERALL: ---",
            font=("Arial", 24, "bold")
        )
        self.overall_result.pack(pady=10)

        # ---------------- SMU1 RESULTS ----------------

        smu1_frame = ttk.LabelFrame(
            right,
            text="SMU1 Results",
            padding=15
        )
        smu1_frame.pack(fill="x", pady=10)

        self.smu1_voltage_label = ttk.Label(
            smu1_frame,
            text="Voltage: ---"
        )
        self.smu1_voltage_label.pack(anchor="w")

        self.smu1_current_label = ttk.Label(
            smu1_frame,
            text="Current: ---"
        )
        self.smu1_current_label.pack(anchor="w")

        self.smu1_status_label = ttk.Label(
            smu1_frame,
            text="Status: ---",
            font=("Arial", 11, "bold")
        )
        self.smu1_status_label.pack(anchor="w", pady=5)

        # ---------------- SMU2 RESULTS ----------------

        smu2_frame = ttk.LabelFrame(
            right,
            text="SMU2 Results",
            padding=15
        )
        smu2_frame.pack(fill="x", pady=10)

        self.smu2_voltage_label = ttk.Label(
            smu2_frame,
            text="Voltage: ---"
        )
        self.smu2_voltage_label.pack(anchor="w")

        self.smu2_current_label = ttk.Label(
            smu2_frame,
            text="Current: ---"
        )
        self.smu2_current_label.pack(anchor="w")

        self.smu2_status_label = ttk.Label(
            smu2_frame,
            text="Status: ---",
            font=("Arial", 11, "bold")
        )
        self.smu2_status_label.pack(anchor="w", pady=5)

    # ======================================================
    # START TEST
    # ======================================================

    def start_test(self):

        self.run_button.config(state="disabled")

        self.status_label.config(
            text="RUNNING"
        )

        threading.Thread(
            target=self.worker,
            daemon=True
        ).start()

    # ======================================================
    # WORKER THREAD
    # ======================================================

    def worker(self):

        try:

            results = run_power_supply_current_test(

                smu1_resource=self.smu1.get(),
                smu2_resource=self.smu2.get(),

                voltage_level=float(
                    self.voltage.get()
                ),

                max_quiescent_current=float(
                    self.max_iq.get()
                ) / 1000,

                max_test_current=float(
                    self.current_limit.get()
                ) / 1000,

                sample_count=int(
                    self.sample_count.get()
                ),

                sample_delay=float(
                    self.sample_delay.get()
                )
            )

            self.root.after(
                0,
                lambda: self.update_results(results)
            )

        except Exception as e:

            self.root.after(
                0,
                lambda: self.fail(str(e))
            )

    # ======================================================
    # UPDATE RESULTS
    # ======================================================

    def update_results(self, r):

        self.smu1_voltage_label.config(
            text=f"Voltage: {r['smu1_voltage']:.6f} V"
        )

        self.smu1_current_label.config(
            text=f"Current: {r['smu1_current_ma']:.6f} mA"
        )

        self.smu1_status_label.config(
            text=f"Status: {'PASS' if r['smu1_pass'] else 'FAIL'}",
            foreground="green" if r["smu1_pass"] else "red"
        )

        self.smu2_voltage_label.config(
            text=f"Voltage: {r['smu2_voltage']:.6f} V"
        )

        self.smu2_current_label.config(
            text=f"Current: {r['smu2_current_ma']:.6f} mA"
        )

        self.smu2_status_label.config(
            text=f"Status: {'PASS' if r['smu2_pass'] else 'FAIL'}",
            foreground="green" if r["smu2_pass"] else "red"
        )

        if r["overall_pass"]:

            self.overall_result.config(
                text="OVERALL: PASS",
                foreground="green"
            )

        else:

            self.overall_result.config(
                text="OVERALL: FAIL",
                foreground="red"
            )

        self.status_label.config(
            text="COMPLETE"
        )

        self.run_button.config(
            state="normal"
        )

    # ======================================================
    # ERROR HANDLER
    # ======================================================

    def fail(self, msg):

        messagebox.showerror(
            "Error",
            msg
        )

        self.status_label.config(
            text="FAIL"
        )

        self.run_button.config(
            state="normal"
        )

    # ======================================================
    # MAIN
    # ======================================================


if __name__ == "__main__":

    root = tk.Tk()

    app = QuiescentCurrentGUI(root)

    root.mainloop()


