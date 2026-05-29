import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import math
import numpy as np

import nidcpower
import nidmm

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


PS_RESOURCE = "PXI4110"
SMU_RESOURCE = "SMU"
DMM_RESOURCE = "PXI4080"

PS_POS_CHANNEL = "1"
PS_NEG_CHANNEL = "2"

DEFAULT_VDD = 15.0
DEFAULT_VEE = -15.0

PS_CURRENT_LIMIT = 0.1
SMU_CURRENT_LIMIT = 1e-3

SWEEP_START_MV = -10.0
SWEEP_STOP_MV = 10.0
SWEEP_STEP_MV = 1.0

SUPPLY_SETTLE_DELAY = 1.0
INPUT_SETTLE_DELAY = 0.20

DMM_RANGE = 10.0
DMM_DIGITS = 6.5


def enable_dual_dut_supply(ps_session, vdd, vee, ps_pos_channel, ps_neg_channel, current_limit):
    pos_ch = ps_session.channels[str(ps_pos_channel)]
    neg_ch = ps_session.channels[str(ps_neg_channel)]

    pos_ch.voltage_level = float(vdd)
    pos_ch.current_limit = float(current_limit)
    neg_ch.voltage_level = float(vee)
    neg_ch.current_limit = float(current_limit)

    pos_ch.output_enabled = True
    pos_ch.output_connected = True
    neg_ch.output_enabled = True
    neg_ch.output_connected = True

    return pos_ch, neg_ch


def disable_dual_dut_supply(ps_session, ps_pos_channel, ps_neg_channel):
    for ch_num in (ps_pos_channel, ps_neg_channel):
        try:
            ch = ps_session.channels[str(ch_num)]
            ch.voltage_level = 0.0
            time.sleep(0.2)
            ch.output_enabled = False
            ch.output_connected = False
        except Exception:
            pass


def read_supply_channel(ch):
    return {
        "voltage_V": ch.measure(nidcpower.MeasurementTypes.VOLTAGE),
        "current_A": ch.measure(nidcpower.MeasurementTypes.CURRENT),
    }


def configure_input_smu(smu_session, current_limit):
    smu_session.source_mode = nidcpower.SourceMode.SINGLE_POINT
    smu_session.output_function = nidcpower.OutputFunction.DC_VOLTAGE
    smu_session.voltage_level_range = 1.0
    smu_session.current_limit = float(current_limit)
    smu_session.voltage_level = 0.0
    smu_session.output_enabled = True


def disable_input_smu(smu_session):
    try:
        smu_session.voltage_level = 0.0
        time.sleep(0.2)
        smu_session.output_enabled = False
    except Exception:
        pass


def generate_sweep_mV(start_mV, stop_mV, step_mV):
    if step_mV == 0:
        raise ValueError("Sweep step cannot be 0.")

    values = []

    if start_mV < stop_mV and step_mV < 0:
        step_mV = abs(step_mV)
    if start_mV > stop_mV and step_mV > 0:
        step_mV = -step_mV

    v = start_mV

    if step_mV > 0:
        while v <= stop_mV + 1e-12:
            values.append(round(v, 9))
            v += step_mV
    else:
        while v >= stop_mV - 1e-12:
            values.append(round(v, 9))
            v += step_mV

    return values


def safe_dmm_read(dmm_session, retries=3, delay=0.15):
    last_value = None

    for _ in range(retries):
        value = dmm_session.read()
        last_value = value

        if value is not None:
            try:
                value = float(value)
                if not math.isnan(value):
                    return value
            except Exception:
                pass

        time.sleep(delay)

    raise RuntimeError("DMM returned invalid value/NaN after retries. Last value: {}".format(last_value))


def run_transfer_curve_test(params):
    ps_session = None
    smu_session = None
    dmm_session = None

    try:
        print("\n==============================")
        print("Starting Transfer Curve Test")
        print("==============================")

        # Open/configure DMM FIRST, same style as simple offset test
        dmm_session = nidmm.Session(params["dmm_resource"])
        dmm_session.configure_measurement_digits(
            nidmm.Function.DC_VOLTS,
            params["dmm_range"],
            DMM_DIGITS
        )
        time.sleep(0.5)

        dummy = safe_dmm_read(dmm_session, retries=3)
        print("DMM dummy read = {:.6f} mV".format(dummy * 1000.0))

        # Then open power supplies and SMU
        ps_session = nidcpower.Session(params["ps_resource"], reset=params["reset"])
        smu_session = nidcpower.Session(params["smu_resource"], reset=params["reset"])

        pos_ch, neg_ch = enable_dual_dut_supply(
            ps_session=ps_session,
            vdd=params["vdd"],
            vee=params["vee"],
            ps_pos_channel=params["ps_pos_channel"],
            ps_neg_channel=params["ps_neg_channel"],
            current_limit=params["ps_current_limit"]
        )

        configure_input_smu(
            smu_session=smu_session,
            current_limit=params["smu_current_limit"]
        )

        vin_mV_list = generate_sweep_mV(
            params["start_mV"],
            params["stop_mV"],
            params["step_mV"]
        )

        vin_V = []
        vout_V = []

        with ps_session.initiate():
            time.sleep(params["supply_settle_delay"])

            power_up = {
                "vplus": read_supply_channel(pos_ch),
                "vminus": read_supply_channel(neg_ch)
            }

            print("Power-up readback:")
            print("V+ = {:.6f} V, I+ = {:.6f} mA".format(
                power_up["vplus"]["voltage_V"],
                power_up["vplus"]["current_A"] * 1000.0
            ))
            print("V- = {:.6f} V, I- = {:.6f} mA".format(
                power_up["vminus"]["voltage_V"],
                power_up["vminus"]["current_A"] * 1000.0
            ))

            # Initiate SMU once, no nested context manager
            smu_session.initiate()
            time.sleep(0.3)

            for vin_mV in vin_mV_list:
                vin = vin_mV / 1000.0

                smu_session.voltage_level = vin
                time.sleep(params["input_settle_delay"])

                vin_meas = smu_session.measure(nidcpower.MeasurementTypes.VOLTAGE)
                vout = safe_dmm_read(dmm_session, retries=3)

                print(
                    "VIN set = {: .6f} mV | VIN measured = {: .6f} mV | VOUT = {: .6f} mV".format(
                        vin * 1000.0,
                        vin_meas * 1000.0,
                        vout * 1000.0
                    )
                )

                vin_V.append(float(vin_meas))
                vout_V.append(float(vout))

        if len(vout_V) < 2:
            raise RuntimeError("Not enough VOUT values were collected.")

        vin_arr = np.array(vin_V, dtype=float)
        vout_arr = np.array(vout_V, dtype=float)

        if np.any(np.isnan(vin_arr)) or np.any(np.isnan(vout_arr)):
            raise RuntimeError("Collected data contains NaN values.")

        slope, intercept = np.polyfit(vin_arr, vout_arr, 1)

        fitted = slope * vin_arr + intercept
        residuals = vout_arr - fitted

        ss_res = np.sum(residuals ** 2)
        ss_tot = np.sum((vout_arr - np.mean(vout_arr)) ** 2)
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot != 0 else 1.0

        return {
            "error": None,
            "chip_name": params["chip_name"],
            "vin_mV": vin_arr * 1000.0,
            "vout_mV": vout_arr * 1000.0,
            "ideal_mV": vin_arr * 1000.0,
            "fit_mV": fitted * 1000.0,
            "slope": slope,
            "offset_mV": intercept * 1000.0,
            "r_squared": r_squared,
            "power_up": power_up,
            "points": len(vin_arr)
        }

    except Exception as e:
        print("\nTEST ERROR:")
        print(str(e))
        return {"error": str(e)}

    finally:
        if smu_session is not None:
            disable_input_smu(smu_session)

        if ps_session is not None:
            disable_dual_dut_supply(
                ps_session,
                params["ps_pos_channel"],
                params["ps_neg_channel"]
            )

        for session in (dmm_session, smu_session, ps_session):
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass


class TransferCurveGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Output Offset Voltage Transfer Curve Test")
        self.root.geometry("1250x720")

        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.create_left_panel()
        self.create_right_panel()

    def create_left_panel(self):
        left = ttk.Frame(self.root, padding="10")
        left.grid(row=0, column=0, sticky="nsew")

        title = ttk.Label(left, text="Output Offset Voltage Transfer Curve Test", font=("Arial", 14, "bold"))
        title.pack(fill="x", pady=(0, 12))

        lf_dut = ttk.LabelFrame(left, text="DUT Specifications", padding="10")
        lf_dut.pack(fill="x", pady=(0, 10))
        lf_dut.columnconfigure(1, weight=1)

        ttk.Label(lf_dut, text="Chip name:").grid(row=0, column=0, sticky="w", pady=3)
        self.chip_name_entry = ttk.Entry(lf_dut)
        self.chip_name_entry.grid(row=0, column=1, sticky="ew", pady=3)
        self.chip_name_entry.insert(0, "OPA551")

        ttk.Label(lf_dut, text="V+ / VDD (V):").grid(row=1, column=0, sticky="w", pady=3)
        self.vdd_entry = ttk.Entry(lf_dut, width=12)
        self.vdd_entry.grid(row=1, column=1, sticky="w", pady=3)
        self.vdd_entry.insert(0, str(DEFAULT_VDD))

        ttk.Label(lf_dut, text="V- / VEE (V):").grid(row=2, column=0, sticky="w", pady=3)
        self.vee_entry = ttk.Entry(lf_dut, width=12)
        self.vee_entry.grid(row=2, column=1, sticky="w", pady=3)
        self.vee_entry.insert(0, str(DEFAULT_VEE))

        lf_inst = ttk.LabelFrame(left, text="Instrument Resources", padding="10")
        lf_inst.pack(fill="x", pady=(0, 10))
        lf_inst.columnconfigure(1, weight=1)

        ttk.Label(lf_inst, text="PXI-4110 resource:").grid(row=0, column=0, sticky="w", pady=3)
        self.ps_resource_entry = ttk.Entry(lf_inst)
        self.ps_resource_entry.grid(row=0, column=1, sticky="ew", pady=3)
        self.ps_resource_entry.insert(0, PS_RESOURCE)

        ttk.Label(lf_inst, text="Input SMU resource:").grid(row=1, column=0, sticky="w", pady=3)
        self.smu_resource_entry = ttk.Entry(lf_inst)
        self.smu_resource_entry.grid(row=1, column=1, sticky="ew", pady=3)
        self.smu_resource_entry.insert(0, SMU_RESOURCE)

        ttk.Label(lf_inst, text="DMM resource:").grid(row=2, column=0, sticky="w", pady=3)
        self.dmm_resource_entry = ttk.Entry(lf_inst)
        self.dmm_resource_entry.grid(row=2, column=1, sticky="ew", pady=3)
        self.dmm_resource_entry.insert(0, DMM_RESOURCE)

        ttk.Label(lf_inst, text="V+ channel:").grid(row=3, column=0, sticky="w", pady=3)
        self.ps_pos_channel_entry = ttk.Entry(lf_inst, width=10)
        self.ps_pos_channel_entry.grid(row=3, column=1, sticky="w", pady=3)
        self.ps_pos_channel_entry.insert(0, PS_POS_CHANNEL)

        ttk.Label(lf_inst, text="V- channel:").grid(row=4, column=0, sticky="w", pady=3)
        self.ps_neg_channel_entry = ttk.Entry(lf_inst, width=10)
        self.ps_neg_channel_entry.grid(row=4, column=1, sticky="w", pady=3)
        self.ps_neg_channel_entry.insert(0, PS_NEG_CHANNEL)

        lf_sweep = ttk.LabelFrame(left, text="Sweep Conditions", padding="10")
        lf_sweep.pack(fill="x", pady=(0, 10))
        lf_sweep.columnconfigure(1, weight=1)

        entries = [
            ("Start voltage (mV):", "start_entry", SWEEP_START_MV),
            ("Stop voltage (mV):", "stop_entry", SWEEP_STOP_MV),
            ("Step voltage (mV):", "step_entry", SWEEP_STEP_MV),
            ("SMU current limit (mA):", "smu_current_limit_entry", SMU_CURRENT_LIMIT * 1e3),
            ("PS current limit per rail (A):", "ps_current_limit_entry", PS_CURRENT_LIMIT),
            ("Supply settle (s):", "supply_settle_entry", SUPPLY_SETTLE_DELAY),
            ("Input settle (s):", "input_settle_entry", INPUT_SETTLE_DELAY),
            ("DMM range (V):", "dmm_range_entry", DMM_RANGE),
        ]

        for row, (label, attr, default) in enumerate(entries):
            ttk.Label(lf_sweep, text=label).grid(row=row, column=0, sticky="w", pady=3)
            entry = ttk.Entry(lf_sweep, width=12)
            entry.grid(row=row, column=1, sticky="w", pady=3)
            entry.insert(0, str(default))
            setattr(self, attr, entry)

        self.reset_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            lf_sweep,
            text="Reset instruments before test",
            variable=self.reset_var
        ).grid(row=len(entries), column=0, columnspan=2, sticky="w", pady=3)

        self.status_label = ttk.Label(
            left,
            text="Status: READY",
            background="#d4edda",
            padding=8,
            anchor="center"
        )
        self.status_label.pack(fill="x", pady=(10, 10))

        buttons = ttk.Frame(left)
        buttons.pack(fill="x")

        self.start_button = ttk.Button(buttons, text="Start Transfer Curve", command=self.start_thread)
        self.start_button.pack(side="left", padx=(0, 8))

        self.clear_button = ttk.Button(buttons, text="Clear Results", command=self.clear_results)
        self.clear_button.pack(side="left")

    def create_right_panel(self):
        right = ttk.Frame(self.root, padding="10")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        self.summary_label = ttk.Label(
            right,
            text="Gain: --      Offset: --      R²: --",
            font=("Arial", 12, "bold"),
            padding=8,
            anchor="center"
        )
        self.summary_label.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.fig = Figure(figsize=(7.2, 4.2), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Transfer Curve")
        self.ax.set_xlabel("Input Voltage VIN (mV)")
        self.ax.set_ylabel("Output Voltage VOUT (mV)")
        self.ax.grid(True)

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew", pady=(0, 8))

        table_frame = ttk.Frame(right)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        columns = ("point", "vin", "vout", "ideal", "error")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=9)

        for col, text, width in [
            ("point", "Point", 70),
            ("vin", "VIN Measured (mV)", 140),
            ("vout", "VOUT (mV)", 120),
            ("ideal", "Ideal (mV)", 120),
            ("error", "VOUT - Ideal (mV)", 150),
        ]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="center")

        self.tree.grid(row=0, column=0, sticky="nsew")

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=y_scroll.set)
        y_scroll.grid(row=0, column=1, sticky="ns")

    def get_inputs(self):
        return {
            "chip_name": self.chip_name_entry.get().strip() or "DUT",
            "vdd": float(self.vdd_entry.get()),
            "vee": float(self.vee_entry.get()),
            "ps_resource": self.ps_resource_entry.get().strip(),
            "smu_resource": self.smu_resource_entry.get().strip(),
            "dmm_resource": self.dmm_resource_entry.get().strip(),
            "ps_pos_channel": self.ps_pos_channel_entry.get().strip(),
            "ps_neg_channel": self.ps_neg_channel_entry.get().strip(),
            "start_mV": float(self.start_entry.get()),
            "stop_mV": float(self.stop_entry.get()),
            "step_mV": float(self.step_entry.get()),
            "smu_current_limit": float(self.smu_current_limit_entry.get()) * 1e-3,
            "ps_current_limit": float(self.ps_current_limit_entry.get()),
            "supply_settle_delay": float(self.supply_settle_entry.get()),
            "input_settle_delay": float(self.input_settle_entry.get()),
            "dmm_range": float(self.dmm_range_entry.get()),
            "reset": self.reset_var.get(),
        }

    def start_thread(self):
        try:
            self.params = self.get_inputs()
        except ValueError as e:
            messagebox.showerror("Input Error", str(e))
            self.update_status(f"Input Error: {e}", "#f8d7da")
            return

        self.start_button.config(state=tk.DISABLED)
        self.clear_button.config(state=tk.DISABLED)
        self.update_status("Status: RUNNING TRANSFER CURVE...", "#fff3cd")

        thread = threading.Thread(target=self.run_test_thread, daemon=True)
        thread.start()

    def run_test_thread(self):
        result = run_transfer_curve_test(self.params)

        if result.get("error"):
            self.root.after(0, self.finish_error, result["error"])
        else:
            self.root.after(0, self.display_result, result)

    def display_result(self, r):
        self.summary_label.config(
            text=(
                f"Gain: {r['slope']:.6f}      "
                f"Offset: {r['offset_mV']:.6f} mV      "
                f"R²: {r['r_squared']:.6f}      "
                f"Points: {r['points']}"
            )
        )

        for item in self.tree.get_children():
            self.tree.delete(item)

        for idx, (vin, vout, ideal) in enumerate(zip(r["vin_mV"], r["vout_mV"], r["ideal_mV"]), start=1):
            self.tree.insert("", tk.END, values=(
                idx,
                f"{vin:.6f}",
                f"{vout:.6f}",
                f"{ideal:.6f}",
                f"{vout - ideal:.6f}",
            ))

        self.ax.clear()
        self.ax.set_title(f"{r['chip_name']} Transfer Curve")
        self.ax.set_xlabel("Input Voltage VIN (mV)")
        self.ax.set_ylabel("Output Voltage VOUT (mV)")
        self.ax.grid(True)

        self.ax.plot(r["vin_mV"], r["vout_mV"], marker="o", label="Measured")
        self.ax.plot(r["vin_mV"], r["ideal_mV"], linestyle="--", label="Ideal: VOUT = VIN")
        self.ax.plot(r["vin_mV"], r["fit_mV"], linestyle=":", label="Linear Fit")
        self.ax.axhline(0)
        self.ax.axvline(0)

        self.ax.annotate(
            f"Offset = {r['offset_mV']:.3f} mV",
            xy=(0, r["offset_mV"]),
            xytext=(5, r["offset_mV"] + 2),
            arrowprops=dict(arrowstyle="->")
        )

        self.ax.legend()
        self.canvas.draw()

        self.update_status("Status: DONE", "#d4edda")
        self.start_button.config(state=tk.NORMAL)
        self.clear_button.config(state=tk.NORMAL)

    def finish_error(self, error_message):
        self.update_status("Status: ERROR", "#f8d7da")
        messagebox.showerror("Test Error", error_message)
        self.start_button.config(state=tk.NORMAL)
        self.clear_button.config(state=tk.NORMAL)

    def update_status(self, text, color):
        self.status_label.config(text=text, background=color)

    def clear_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.ax.clear()
        self.ax.set_title("Transfer Curve")
        self.ax.set_xlabel("Input Voltage VIN (mV)")
        self.ax.set_ylabel("Output Voltage VOUT (mV)")
        self.ax.grid(True)
        self.canvas.draw()

        self.summary_label.config(text="Gain: --      Offset: --      R²: --")
        self.update_status("Status: READY", "#d4edda")


if __name__ == "__main__":
    root = tk.Tk()
    app = TransferCurveGUI(root)
    root.mainloop()