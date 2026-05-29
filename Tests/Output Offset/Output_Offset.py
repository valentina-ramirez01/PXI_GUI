import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import statistics

import nidcpower
import nidmm


# ============================================================
# OUTPUT OFFSET VOLTAGE TEST
# PXI-4110 CH1 = +V
# PXI-4110 CH2 = -V
# DMM measures OUT to GND
# ============================================================

PS_RESOURCE = "PXI4110"
DMM_RESOURCE = "PXI4080"

PS_POS_CHANNEL = "1"
PS_NEG_CHANNEL = "2"

DEFAULT_VDD = 15.0
DEFAULT_VEE = -15.0

PS_CURRENT_LIMIT = 0.1
SAMPLE_COUNT = 30

SUPPLY_SETTLE_DELAY = 1.0
MEASURE_DELAY = 0.1

DEFAULT_OFFSET_LIMIT_MV = 3.0


# ---------------- PXI-4110 HELPERS ----------------

def enable_dual_dut_supply(
    ps_session,
    vdd,
    vee,
    ps_pos_channel=PS_POS_CHANNEL,
    ps_neg_channel=PS_NEG_CHANNEL,
    current_limit=PS_CURRENT_LIMIT
):
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


def read_supply_channel(ch):
    return {
        "voltage_V": ch.measure(nidcpower.MeasurementTypes.VOLTAGE),
        "current_A": ch.measure(nidcpower.MeasurementTypes.CURRENT),
    }


def disable_dual_dut_supply(ps_session, ps_pos_channel=PS_POS_CHANNEL, ps_neg_channel=PS_NEG_CHANNEL):
    for ch_num in (ps_pos_channel, ps_neg_channel):
        try:
            ch = ps_session.channels[str(ch_num)]
            ch.voltage_level = 0.0
            time.sleep(0.2)
            ch.output_enabled = False
            ch.output_connected = False
        except Exception:
            pass


# ---------------- TEST FUNCTION ----------------

def run_output_offset_test(
    chip_name,
    vdd,
    vee,
    offset_limit_mv,
    ps_resource,
    dmm_resource,
    ps_pos_channel,
    ps_neg_channel,
    ps_current_limit,
    sample_count,
    supply_settle_delay,
    measure_delay,
    reset=True
):
    ps_session = None
    dmm_session = None

    try:
        ps_session = nidcpower.Session(ps_resource, reset=reset)
        dmm_session = nidmm.Session(dmm_resource)

        pos_ch, neg_ch = enable_dual_dut_supply(
            ps_session=ps_session,
            vdd=vdd,
            vee=vee,
            ps_pos_channel=ps_pos_channel,
            ps_neg_channel=ps_neg_channel,
            current_limit=ps_current_limit
        )

        with ps_session.initiate():
            time.sleep(supply_settle_delay)

            vplus_readback = read_supply_channel(pos_ch)
            vminus_readback = read_supply_channel(neg_ch)

            dmm_session.configure_measurement_digits(
                nidmm.Function.DC_VOLTS,
                10.0,
                6.5
            )

            samples = []
            for _ in range(sample_count):
                samples.append(dmm_session.read())
                time.sleep(measure_delay)

            avg_v = statistics.mean(samples)
            std_v = statistics.stdev(samples) if len(samples) > 1 else 0.0

            avg_mv = avg_v * 1000.0
            std_mv = std_v * 1000.0

            passed = abs(avg_mv) <= offset_limit_mv

            return {
                "chip_name": chip_name,
                "vdd_set": vdd,
                "vee_set": vee,
                "vplus_readback": vplus_readback,
                "vminus_readback": vminus_readback,
                "offset_avg_V": avg_v,
                "offset_avg_mV": avg_mv,
                "offset_std_V": std_v,
                "offset_std_mV": std_mv,
                "offset_limit_mV": offset_limit_mv,
                "sample_count": sample_count,
                "status": "PASS" if passed else "FAIL",
                "error": None
            }

    except Exception as e:
        return {
            "error": str(e)
        }

    finally:
        if ps_session is not None:
            disable_dual_dut_supply(
                ps_session,
                ps_pos_channel=ps_pos_channel,
                ps_neg_channel=ps_neg_channel
            )

        if dmm_session is not None:
            try:
                dmm_session.close()
            except Exception:
                pass

        if ps_session is not None:
            try:
                ps_session.close()
            except Exception:
                pass


# ---------------- GUI ----------------

class OutputOffsetGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Output Offset Voltage Test")
        self.root.geometry("1050x620")

        self.run_counter = 0

        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.create_left_panel()
        self.create_right_panel()

    def create_left_panel(self):
        left = ttk.Frame(self.root, padding="10")
        left.grid(row=0, column=0, sticky="nsew")

        title = ttk.Label(left, text="Output Offset Voltage Test", font=("Arial", 15, "bold"))
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

        ttk.Label(lf_inst, text="DMM resource:").grid(row=1, column=0, sticky="w", pady=3)
        self.dmm_resource_entry = ttk.Entry(lf_inst)
        self.dmm_resource_entry.grid(row=1, column=1, sticky="ew", pady=3)
        self.dmm_resource_entry.insert(0, DMM_RESOURCE)

        ttk.Label(lf_inst, text="V+ channel:").grid(row=2, column=0, sticky="w", pady=3)
        self.ps_pos_channel_entry = ttk.Entry(lf_inst, width=10)
        self.ps_pos_channel_entry.grid(row=2, column=1, sticky="w", pady=3)
        self.ps_pos_channel_entry.insert(0, PS_POS_CHANNEL)

        ttk.Label(lf_inst, text="V- channel:").grid(row=3, column=0, sticky="w", pady=3)
        self.ps_neg_channel_entry = ttk.Entry(lf_inst, width=10)
        self.ps_neg_channel_entry.grid(row=3, column=1, sticky="w", pady=3)
        self.ps_neg_channel_entry.insert(0, PS_NEG_CHANNEL)

        lf_test = ttk.LabelFrame(left, text="Test Conditions", padding="10")
        lf_test.pack(fill="x", pady=(0, 10))
        lf_test.columnconfigure(1, weight=1)

        ttk.Label(lf_test, text="Offset limit (mV):").grid(row=0, column=0, sticky="w", pady=3)
        self.offset_limit_entry = ttk.Entry(lf_test, width=12)
        self.offset_limit_entry.grid(row=0, column=1, sticky="w", pady=3)
        self.offset_limit_entry.insert(0, str(DEFAULT_OFFSET_LIMIT_MV))

        ttk.Label(lf_test, text="PS current limit per rail (A):").grid(row=1, column=0, sticky="w", pady=3)
        self.ps_current_limit_entry = ttk.Entry(lf_test, width=12)
        self.ps_current_limit_entry.grid(row=1, column=1, sticky="w", pady=3)
        self.ps_current_limit_entry.insert(0, str(PS_CURRENT_LIMIT))

        ttk.Label(lf_test, text="Samples:").grid(row=2, column=0, sticky="w", pady=3)
        self.sample_count_entry = ttk.Entry(lf_test, width=12)
        self.sample_count_entry.grid(row=2, column=1, sticky="w", pady=3)
        self.sample_count_entry.insert(0, str(SAMPLE_COUNT))

        ttk.Label(lf_test, text="Supply settle (s):").grid(row=3, column=0, sticky="w", pady=3)
        self.supply_settle_entry = ttk.Entry(lf_test, width=12)
        self.supply_settle_entry.grid(row=3, column=1, sticky="w", pady=3)
        self.supply_settle_entry.insert(0, str(SUPPLY_SETTLE_DELAY))

        ttk.Label(lf_test, text="Measure delay (s):").grid(row=4, column=0, sticky="w", pady=3)
        self.measure_delay_entry = ttk.Entry(lf_test, width=12)
        self.measure_delay_entry.grid(row=4, column=1, sticky="w", pady=3)
        self.measure_delay_entry.insert(0, str(MEASURE_DELAY))

        self.reset_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            lf_test,
            text="Reset instruments before test",
            variable=self.reset_var
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=3)

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

        self.start_button = ttk.Button(buttons, text="Start Test", command=self.start_thread)
        self.start_button.pack(side="left", padx=(0, 8))

        self.clear_button = ttk.Button(buttons, text="Clear Results", command=self.clear_results)
        self.clear_button.pack(side="left")

    def create_right_panel(self):
        right = ttk.Frame(self.root, padding="10")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        columns = (
            "run", "chip", "vdd", "vee", "vplus_read", "vminus_read",
            "offset_mv", "std_mv", "limit_mv", "samples", "result"
        )

        self.tree = ttk.Treeview(right, columns=columns, show="headings")

        headings = {
            "run": "Run",
            "chip": "Chip",
            "vdd": "V+ Set",
            "vee": "V- Set",
            "vplus_read": "V+ Readback",
            "vminus_read": "V- Readback",
            "offset_mv": "Offset Avg (mV)",
            "std_mv": "Std Dev (mV)",
            "limit_mv": "Limit (mV)",
            "samples": "Samples",
            "result": "Result",
        }

        widths = {
            "run": 45,
            "chip": 90,
            "vdd": 80,
            "vee": 80,
            "vplus_read": 120,
            "vminus_read": 120,
            "offset_mv": 120,
            "std_mv": 110,
            "limit_mv": 90,
            "samples": 75,
            "result": 90,
        }

        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="center")

        self.tree.tag_configure("pass", background="#d4edda")
        self.tree.tag_configure("fail", background="#f8d7da")

        self.tree.grid(row=0, column=0, sticky="nsew")

        y_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=y_scroll.set)
        y_scroll.grid(row=0, column=1, sticky="ns")

        x_scroll = ttk.Scrollbar(right, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(xscroll=x_scroll.set)
        x_scroll.grid(row=1, column=0, sticky="ew")

    def get_inputs(self):
        return {
            "chip_name": self.chip_name_entry.get().strip() or "DUT",
            "vdd": float(self.vdd_entry.get()),
            "vee": float(self.vee_entry.get()),
            "offset_limit_mv": float(self.offset_limit_entry.get()),
            "ps_resource": self.ps_resource_entry.get().strip(),
            "dmm_resource": self.dmm_resource_entry.get().strip(),
            "ps_pos_channel": self.ps_pos_channel_entry.get().strip(),
            "ps_neg_channel": self.ps_neg_channel_entry.get().strip(),
            "ps_current_limit": float(self.ps_current_limit_entry.get()),
            "sample_count": int(self.sample_count_entry.get()),
            "supply_settle_delay": float(self.supply_settle_entry.get()),
            "measure_delay": float(self.measure_delay_entry.get()),
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
        self.update_status("Status: RUNNING...", "#fff3cd")

        thread = threading.Thread(target=self.run_test_thread, daemon=True)
        thread.start()

    def run_test_thread(self):
        p = self.params

        result = run_output_offset_test(
            chip_name=p["chip_name"],
            vdd=p["vdd"],
            vee=p["vee"],
            offset_limit_mv=p["offset_limit_mv"],
            ps_resource=p["ps_resource"],
            dmm_resource=p["dmm_resource"],
            ps_pos_channel=p["ps_pos_channel"],
            ps_neg_channel=p["ps_neg_channel"],
            ps_current_limit=p["ps_current_limit"],
            sample_count=p["sample_count"],
            supply_settle_delay=p["supply_settle_delay"],
            measure_delay=p["measure_delay"],
            reset=p["reset"],
        )

        if result.get("error"):
            self.root.after(0, self.finish_error, result["error"])
        else:
            self.root.after(0, self.display_result, result)

    def display_result(self, r):
        self.run_counter += 1

        passed = r["status"] == "PASS"
        tag = "pass" if passed else "fail"

        vplus = r["vplus_readback"]
        vminus = r["vminus_readback"]

        self.tree.insert(
            "",
            tk.END,
            values=(
                self.run_counter,
                r["chip_name"],
                f"{r['vdd_set']:.3f}",
                f"{r['vee_set']:.3f}",
                f"{vplus['voltage_V']:.4f} V / {vplus['current_A'] * 1e3:.3f} mA",
                f"{vminus['voltage_V']:.4f} V / {vminus['current_A'] * 1e3:.3f} mA",
                f"{r['offset_avg_mV']:.6f}",
                f"{r['offset_std_mV']:.6f}",
                f"±{r['offset_limit_mV']:.3f}",
                r["sample_count"],
                r["status"],
            ),
            tags=(tag,)
        )

        if passed:
            self.update_status("Status: PASS", "#d4edda")
        else:
            self.update_status("Status: FAIL", "#f8d7da")

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

        self.run_counter = 0
        self.update_status("Status: READY", "#d4edda")


if __name__ == "__main__":
    root = tk.Tk()
    app = OutputOffsetGUI(root)
    root.mainloop()