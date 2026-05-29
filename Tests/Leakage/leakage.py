import tkinter as tk
from tkinter import ttk, messagebox
import threading

# ============================================================
# COMBINED OPA551 LEAKAGE GUI + REAL TEST CODE
# No external leakage_test.py import needed.
# Datasheet-style: V+ = +15 V, V- = -15 V;
# high leakage forces +V, low leakage forces -V.
# ============================================================

import time
import numpy as np
import nidcpower


# ---------------- DEFAULT CONFIGURATION ----------------

CURRENT_LIMIT = 1e-3          # 1 mA compliance to protect DUT input
LEAKAGE_LIMIT = 10e-6         # 10 uA pass/fail limit

SAMPLE_COUNT = 30             # Real measurements used for result
DUMMY_COUNT = 5               # Throwaway readings to let current settle

INITIAL_SETTLE_DELAY = 1.0    # Wait after forcing voltage before reading
MEASURE_DELAY = 0.1           # Delay between readings
SUPPLY_SETTLE_DELAY = 1.0     # Wait after powering DUT

SMU_RESOURCE = "SMU"          # Change if needed from NI MAX
PS_RESOURCE = "PXI4110"       # Change if needed from NI MAX

# PXI-4110 channels for OPA551 +/- supply
PS_POS_CHANNEL = "1"          # V+ / VDD channel
PS_NEG_CHANNEL = "2"          # V- / VEE channel
PS_CHANNEL = PS_POS_CHANNEL   # Backward-compatible name

DEFAULT_VDD = 15.0
DEFAULT_VEE = -15.0
PS_CURRENT_LIMIT = 0.1        # DUT supply current limit per rail


# ---------------- SESSION HELPERS ----------------

def open_instrument_sessions(
    smu_resource=SMU_RESOURCE,
    ps_resource=PS_RESOURCE,
    reset=True
):
    """
    Open and return power supply and SMU sessions.
    """
    ps_session = nidcpower.Session(ps_resource, reset=reset)
    smu_session = nidcpower.Session(smu_resource, reset=reset)
    return ps_session, smu_session


def close_instrument_sessions(ps_session=None, smu_session=None):
    """
    Safely close sessions.
    """
    if smu_session is not None:
        try:
            smu_session.close()
        except Exception:
            pass

    if ps_session is not None:
        try:
            ps_session.close()
        except Exception:
            pass


# ---------------- POWER SUPPLY FUNCTIONS ----------------

def enable_dut_supply(
    ps_session,
    vdd,
    ps_channel=PS_POS_CHANNEL,
    current_limit=PS_CURRENT_LIMIT
):
    """
    Enable one PXI-4110 channel. Kept for compatibility with old code.
    """
    ch = ps_session.channels[str(ps_channel)]
    ch.voltage_level = float(vdd)
    ch.current_limit = float(current_limit)
    ch.output_enabled = True
    ch.output_connected = True
    return ch


def enable_dual_dut_supply(
    ps_session,
    vdd=DEFAULT_VDD,
    vee=DEFAULT_VEE,
    ps_pos_channel=PS_POS_CHANNEL,
    ps_neg_channel=PS_NEG_CHANNEL,
    current_limit=PS_CURRENT_LIMIT
):
    """
    Enable both DUT rails using PXI-4110 channels.

    For your setup:
      V+  -> PXI-4110 channel 1 at +15 V
      V-  -> PXI-4110 channel 2 at -15 V
      GND -> PXI-4110 common/LO reference
    """
    pos_ch = ps_session.channels[str(ps_pos_channel)]
    neg_ch = ps_session.channels[str(ps_neg_channel)]

    # Program voltage/current before connecting/enabling outputs.
    pos_ch.voltage_level = float(vdd)
    pos_ch.current_limit = float(current_limit)

    neg_ch.voltage_level = float(vee)
    neg_ch.current_limit = float(current_limit)

    pos_ch.output_enabled = True
    pos_ch.output_connected = True
    neg_ch.output_enabled = True
    neg_ch.output_connected = True

    return pos_ch, neg_ch


def read_dut_supply(ps_channel_obj):
    """
    Read one DUT supply channel voltage and current.
    """
    measured_v = ps_channel_obj.measure(nidcpower.MeasurementTypes.VOLTAGE)
    measured_i = ps_channel_obj.measure(nidcpower.MeasurementTypes.CURRENT)
    return {
        "measured_voltage_V": measured_v,
        "measured_current_A": measured_i
    }


def read_dual_dut_supply(pos_channel_obj, neg_channel_obj):
    """
    Read both DUT supply rails.
    """
    return {
        "vplus": read_dut_supply(pos_channel_obj),
        "vminus": read_dut_supply(neg_channel_obj),
    }


def disable_dut_supply(ps_session, ps_channel=PS_POS_CHANNEL):
    """
    Fully disable one DUT supply output. Kept for compatibility with old code.
    """
    ch = ps_session.channels[str(ps_channel)]
    try:
        ch.voltage_level = 0.0
        time.sleep(0.2)
    except Exception:
        pass
    ch.output_enabled = False
    ch.output_connected = False
    return {"channel": str(ps_channel), "status": "OFF"}


def disable_dual_dut_supply(
    ps_session,
    ps_pos_channel=PS_POS_CHANNEL,
    ps_neg_channel=PS_NEG_CHANNEL
):
    """
    Disable both DUT supply rails.
    """
    statuses = {}
    for name, ch_num in (("vplus", ps_pos_channel), ("vminus", ps_neg_channel)):
        try:
            statuses[name] = disable_dut_supply(ps_session, ch_num)
        except Exception as e:
            statuses[name] = {"channel": str(ch_num), "status": "ERROR", "message": str(e)}
    return statuses


# ---------------- SMU CONFIGURATION ----------------

def configure_smu_for_leakage(
    smu_session,
    voltage_level,
    current_limit=CURRENT_LIMIT
):
    """
    Configure SMU to force voltage and measure current.
    """
    smu_session.source_mode = nidcpower.SourceMode.SINGLE_POINT
    smu_session.output_function = nidcpower.OutputFunction.DC_VOLTAGE

    # FIX: SMU default range may be +/-6 V. Set range before forcing +/-15 V.
    smu_session.voltage_level_range = 20.0

    smu_session.current_limit = float(current_limit)
    smu_session.voltage_level = float(voltage_level)
    smu_session.output_enabled = True


def disable_smu_output(smu_session):
    """
    Disable SMU output.
    """
    smu_session.output_enabled = False


# ---------------- MEASUREMENT HELPERS ----------------

def collect_leakage_currents(
    smu_session,
    sample_count=SAMPLE_COUNT,
    dummy_count=DUMMY_COUNT,
    initial_settle_delay=INITIAL_SETTLE_DELAY,
    measure_delay=MEASURE_DELAY
):
    """
    Collect leakage current samples from the SMU.
    Returns a NumPy array of currents.
    """
    currents = []
    time.sleep(initial_settle_delay)

    with smu_session.initiate():
        for _ in range(dummy_count):
            time.sleep(measure_delay)
            smu_session.measure(nidcpower.MeasurementTypes.CURRENT)

        for _ in range(sample_count):
            time.sleep(measure_delay)
            current = smu_session.measure(nidcpower.MeasurementTypes.CURRENT)
            currents.append(current)

    return np.array(currents, dtype=float)


def analyze_leakage_data(
    currents,
    voltage_level,
    test_name,
    leakage_limit=LEAKAGE_LIMIT
):
    """
    Analyze measured currents and return a result dictionary.
    """
    avg_current = float(np.mean(currents))
    min_current = float(np.min(currents))
    max_current = float(np.max(currents))
    status = "NOT PASSED" if abs(avg_current) > leakage_limit else "PASSED"

    return {
        "test": test_name,
        "forced_voltage_V": float(voltage_level),
        "status": status,
        "limit_uA": leakage_limit * 1e6,
        "avg_current_A": avg_current,
        "avg_current_uA": avg_current * 1e6,
        "min_current_A": min_current,
        "min_current_uA": min_current * 1e6,
        "max_current_A": max_current,
        "max_current_uA": max_current * 1e6,
        "sample_count": len(currents)
    }


# ---------------- LEAKAGE TEST FUNCTIONS ----------------

def run_single_leakage_test(
    smu_session,
    voltage_level,
    test_name,
    current_limit=CURRENT_LIMIT,
    leakage_limit=LEAKAGE_LIMIT,
    sample_count=SAMPLE_COUNT,
    dummy_count=DUMMY_COUNT,
    initial_settle_delay=INITIAL_SETTLE_DELAY,
    measure_delay=MEASURE_DELAY
):
    """
    Run one leakage test at a specified forced voltage.
    """
    configure_smu_for_leakage(
        smu_session=smu_session,
        voltage_level=voltage_level,
        current_limit=current_limit
    )

    try:
        currents = collect_leakage_currents(
            smu_session=smu_session,
            sample_count=sample_count,
            dummy_count=dummy_count,
            initial_settle_delay=initial_settle_delay,
            measure_delay=measure_delay
        )
        return analyze_leakage_data(
            currents=currents,
            voltage_level=voltage_level,
            test_name=test_name,
            leakage_limit=leakage_limit
        )
    finally:
        disable_smu_output(smu_session)


def run_input_leakage_high(smu_session, high_force_voltage, **kwargs):
    """
    Run input leakage high test using the user-entered force voltage.
    Example for OPA551 with +/-15 V supplies: +12.5 V.
    """
    return run_single_leakage_test(
        smu_session=smu_session,
        voltage_level=float(high_force_voltage),
        test_name="Input Leakage High",
        **kwargs
    )


def run_input_leakage_low(smu_session, low_force_voltage, **kwargs):
    """
    Run input leakage low test using the user-entered force voltage.
    Example for OPA551 with +/-15 V supplies: -12.5 V.
    """
    return run_single_leakage_test(
        smu_session=smu_session,
        voltage_level=float(low_force_voltage),
        test_name="Input Leakage Low",
        **kwargs
    )


def run_full_leakage_test(
    vdd=DEFAULT_VDD,
    vee=DEFAULT_VEE,
    high_force_voltage=None,
    low_force_voltage=None,
    test_mode="Both ILH and ILL",
    smu_resource=SMU_RESOURCE,
    ps_resource=PS_RESOURCE,
    ps_channel=PS_POS_CHANNEL,
    ps_pos_channel=None,
    ps_neg_channel=PS_NEG_CHANNEL,
    ps_current_limit=PS_CURRENT_LIMIT,
    smu_current_limit=CURRENT_LIMIT,
    leakage_limit=LEAKAGE_LIMIT,
    sample_count=SAMPLE_COUNT,
    dummy_count=DUMMY_COUNT,
    initial_settle_delay=INITIAL_SETTLE_DELAY,
    measure_delay=MEASURE_DELAY,
    supply_settle_delay=SUPPLY_SETTLE_DELAY,
    reset=True
):
    """
    Full leakage test sequence with +/- DUT supply:
    1. Open sessions
    2. Power DUT: V+ = vdd and V- = vee
    3. Run selected leakage test(s): ILH, ILL, or both
       ILH uses high_force_voltage, ILL uses low_force_voltage
    5. Power DUT down
    6. Close sessions

    ps_channel is accepted for backwards compatibility and is treated as ps_pos_channel.
    """
    if ps_pos_channel is None:
        ps_pos_channel = ps_channel

    # If the GUI/user does not provide explicit ILH/ILL force voltages,
    # default to the valid common-mode edges for OPA551:
    # High = V+ - 2.5 V, Low = V- + 2.5 V.
    if high_force_voltage is None:
        high_force_voltage = float(vdd) - 2.5
    if low_force_voltage is None:
        low_force_voltage = float(vee) + 2.5

    ps_session = None
    smu_session = None
    results = {
        "power_up": None,
        "input_leakage_high": None,
        "input_leakage_low": None,
        "power_down": None,
        "error": None
    }

    try:
        ps_session, smu_session = open_instrument_sessions(
            smu_resource=smu_resource,
            ps_resource=ps_resource,
            reset=reset
        )

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
            results["power_up"] = read_dual_dut_supply(pos_ch, neg_ch)

            mode = str(test_mode).strip()

            if mode in ("Both ILH and ILL", "Input Leakage High only"):
                results["input_leakage_high"] = run_input_leakage_high(
                    smu_session=smu_session,
                    high_force_voltage=high_force_voltage,
                    current_limit=smu_current_limit,
                    leakage_limit=leakage_limit,
                    sample_count=sample_count,
                    dummy_count=dummy_count,
                    initial_settle_delay=initial_settle_delay,
                    measure_delay=measure_delay
                )

            if mode == "Both ILH and ILL":
                time.sleep(1.0)

            if mode in ("Both ILH and ILL", "Input Leakage Low only"):
                results["input_leakage_low"] = run_input_leakage_low(
                    smu_session=smu_session,
                    low_force_voltage=low_force_voltage,
                    current_limit=smu_current_limit,
                    leakage_limit=leakage_limit,
                    sample_count=sample_count,
                    dummy_count=dummy_count,
                    initial_settle_delay=initial_settle_delay,
                    measure_delay=measure_delay
                )

            if mode not in ("Both ILH and ILL", "Input Leakage High only", "Input Leakage Low only"):
                raise ValueError(f"Unknown leakage test selection: {mode}")

    except Exception as e:
        results["error"] = str(e)

    finally:
        if ps_session is not None:
            results["power_down"] = disable_dual_dut_supply(
                ps_session=ps_session,
                ps_pos_channel=ps_pos_channel,
                ps_neg_channel=ps_neg_channel
            )
        close_instrument_sessions(ps_session=ps_session, smu_session=smu_session)

    return results




class LeakageTestGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("OPA551 Leakage Test Interface")
        self.root.geometry("1050x650")

        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.run_counter = 0
        self.create_left_panel()
        self.create_right_panel()

    # ============================================================
    # GUI LAYOUT
    # ============================================================
    def create_left_panel(self):
        left_frame = ttk.Frame(self.root, padding="10")
        left_frame.grid(row=0, column=0, sticky="nsew")

        description_text = (
            "This GUI runs the real PXIe leakage test for OPA551 datasheet-style conditions. "
            "PXI-4110 Channel 1 powers V+ and Channel 2 powers V-. The SMU connects to the "
            "pin under test and runs the user-selected test: ILH, ILL, or both. "
            "The force voltages are selected/entered by the user. Results stay displayed after each run."
        )
        desc_label = ttk.Label(left_frame, text=description_text, wraplength=380, justify="left")
        desc_label.pack(fill="x", pady=(0, 12))

        # --- DUT Specifications ---
        lf_dut = ttk.LabelFrame(left_frame, text="DUT Specifications", padding="10")
        lf_dut.pack(fill="x", pady=(0, 10))
        lf_dut.columnconfigure(1, weight=1)

        ttk.Label(lf_dut, text="Chip name:").grid(row=0, column=0, sticky="w", pady=3)
        self.chip_name_entry = ttk.Entry(lf_dut)
        self.chip_name_entry.grid(row=0, column=1, sticky="ew", pady=3)
        self.chip_name_entry.insert(0, "OPA551")

        ttk.Label(lf_dut, text="Pin under test label:").grid(row=1, column=0, sticky="w", pady=3)
        self.pin_label_entry = ttk.Entry(lf_dut)
        self.pin_label_entry.grid(row=1, column=1, sticky="ew", pady=3)
        self.pin_label_entry.insert(0, "IN-")

        ttk.Label(lf_dut, text="V+ / VDD (V):").grid(row=2, column=0, sticky="w", pady=3)
        self.vdd_entry = ttk.Entry(lf_dut, width=10)
        self.vdd_entry.grid(row=2, column=1, sticky="w", pady=3)
        self.vdd_entry.insert(0, str(DEFAULT_VDD))

        ttk.Label(lf_dut, text="V- / VEE (V):").grid(row=11, column=0, sticky="w", pady=3)
        self.vee_entry = ttk.Entry(lf_dut, width=10)
        self.vee_entry.grid(row=11, column=1, sticky="w", pady=3)
        self.vee_entry.insert(0, str(DEFAULT_VEE))

        # --- Instrument Resources ---
        lf_inst = ttk.LabelFrame(left_frame, text="Instrument Resources", padding="10")
        lf_inst.pack(fill="x", pady=(0, 10))
        lf_inst.columnconfigure(1, weight=1)

        ttk.Label(lf_inst, text="SMU resource:").grid(row=0, column=0, sticky="w", pady=3)
        self.smu_resource_entry = ttk.Entry(lf_inst)
        self.smu_resource_entry.grid(row=0, column=1, sticky="ew", pady=3)
        self.smu_resource_entry.insert(0, SMU_RESOURCE)

        ttk.Label(lf_inst, text="PXI-4110 resource:").grid(row=1, column=0, sticky="w", pady=3)
        self.ps_resource_entry = ttk.Entry(lf_inst)
        self.ps_resource_entry.grid(row=1, column=1, sticky="ew", pady=3)
        self.ps_resource_entry.insert(0, PS_RESOURCE)

        ttk.Label(lf_inst, text="V+ channel:").grid(row=2, column=0, sticky="w", pady=3)
        self.ps_pos_channel_entry = ttk.Entry(lf_inst, width=10)
        self.ps_pos_channel_entry.grid(row=2, column=1, sticky="w", pady=3)
        self.ps_pos_channel_entry.insert(0, PS_POS_CHANNEL)

        ttk.Label(lf_inst, text="V- channel:").grid(row=3, column=0, sticky="w", pady=3)
        self.ps_neg_channel_entry = ttk.Entry(lf_inst, width=10)
        self.ps_neg_channel_entry.grid(row=3, column=1, sticky="w", pady=3)
        self.ps_neg_channel_entry.insert(0, PS_NEG_CHANNEL)

        # --- Test Conditions ---
        lf_test = ttk.LabelFrame(left_frame, text="Test Conditions", padding="10")
        lf_test.pack(fill="x", pady=(0, 10))
        lf_test.columnconfigure(1, weight=1)

        ttk.Label(lf_test, text="Leakage test selected:").grid(row=0, column=0, sticky="w", pady=3)
        self.test_select_combo = ttk.Combobox(
            lf_test,
            values=("Both ILH and ILL", "Input Leakage High only", "Input Leakage Low only"),
            state="readonly",
            width=24
        )
        self.test_select_combo.grid(row=0, column=1, sticky="w", pady=3)
        self.test_select_combo.set("Both ILH and ILL")
        self.test_select_combo.bind("<<ComboboxSelected>>", self.update_force_entry_states)

        ttk.Label(lf_test, text="ILH high force voltage (V):").grid(row=1, column=0, sticky="w", pady=3)
        self.high_force_entry = ttk.Entry(lf_test, width=10)
        self.high_force_entry.grid(row=1, column=1, sticky="w", pady=3)
        self.high_force_entry.insert(0, "12.5")

        ttk.Label(lf_test, text="ILL low force voltage (V):").grid(row=2, column=0, sticky="w", pady=3)
        self.low_force_entry = ttk.Entry(lf_test, width=10)
        self.low_force_entry.grid(row=2, column=1, sticky="w", pady=3)
        self.low_force_entry.insert(0, "-12.5")

        ttk.Label(lf_test, text="Leakage limit:").grid(row=3, column=0, sticky="w", pady=3)
        limit_frame = ttk.Frame(lf_test)
        limit_frame.grid(row=3, column=1, sticky="w", pady=3)

        self.leakage_limit_entry = ttk.Entry(limit_frame, width=10)
        self.leakage_limit_entry.pack(side="left")
        self.leakage_limit_entry.insert(0, str(LEAKAGE_LIMIT * 1e6))

        self.leakage_unit_combo = ttk.Combobox(
            limit_frame,
            values=("nA", "uA", "mA"),
            state="readonly",
            width=5
        )
        self.leakage_unit_combo.pack(side="left", padx=(6, 0))
        self.leakage_unit_combo.set("uA")

        ttk.Label(lf_test, text="SMU current limit (mA):").grid(row=4, column=0, sticky="w", pady=3)
        self.smu_current_limit_entry = ttk.Entry(lf_test, width=10)
        self.smu_current_limit_entry.grid(row=4, column=1, sticky="w", pady=3)
        self.smu_current_limit_entry.insert(0, str(CURRENT_LIMIT * 1e3))

        ttk.Label(lf_test, text="PS current limit per rail (A):").grid(row=5, column=0, sticky="w", pady=3)
        self.ps_current_limit_entry = ttk.Entry(lf_test, width=10)
        self.ps_current_limit_entry.grid(row=5, column=1, sticky="w", pady=3)
        self.ps_current_limit_entry.insert(0, str(PS_CURRENT_LIMIT))

        ttk.Label(lf_test, text="Samples:").grid(row=6, column=0, sticky="w", pady=3)
        self.sample_count_entry = ttk.Entry(lf_test, width=10)
        self.sample_count_entry.grid(row=6, column=1, sticky="w", pady=3)
        self.sample_count_entry.insert(0, str(SAMPLE_COUNT))

        ttk.Label(lf_test, text="Dummy readings:").grid(row=7, column=0, sticky="w", pady=3)
        self.dummy_count_entry = ttk.Entry(lf_test, width=10)
        self.dummy_count_entry.grid(row=7, column=1, sticky="w", pady=3)
        self.dummy_count_entry.insert(0, str(DUMMY_COUNT))

        ttk.Label(lf_test, text="Measure delay (s):").grid(row=8, column=0, sticky="w", pady=3)
        self.measure_delay_entry = ttk.Entry(lf_test, width=10)
        self.measure_delay_entry.grid(row=8, column=1, sticky="w", pady=3)
        self.measure_delay_entry.insert(0, str(MEASURE_DELAY))

        ttk.Label(lf_test, text="Initial settle (s):").grid(row=9, column=0, sticky="w", pady=3)
        self.initial_settle_entry = ttk.Entry(lf_test, width=10)
        self.initial_settle_entry.grid(row=9, column=1, sticky="w", pady=3)
        self.initial_settle_entry.insert(0, str(INITIAL_SETTLE_DELAY))

        ttk.Label(lf_test, text="Supply settle (s):").grid(row=10, column=0, sticky="w", pady=3)
        self.supply_settle_entry = ttk.Entry(lf_test, width=10)
        self.supply_settle_entry.grid(row=10, column=1, sticky="w", pady=3)
        self.supply_settle_entry.insert(0, str(SUPPLY_SETTLE_DELAY))

        self.reset_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(lf_test, text="Reset instruments before test", variable=self.reset_var).grid(
            row=11, column=0, columnspan=2, sticky="w", pady=3
        )

        # --- Status and Controls ---
        self.status_label = ttk.Label(
            left_frame,
            text="Status: READY",
            background="#d4edda",
            padding=7,
            anchor="center"
        )
        self.status_label.pack(fill="x", pady=(10, 10))

        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill="x")

        self.start_button = ttk.Button(button_frame, text="Start Leakage Test", command=self.start_thread)
        self.start_button.pack(side="left", padx=(0, 8))

        self.clear_button = ttk.Button(button_frame, text="Clear Results", command=self.clear_results)
        self.clear_button.pack(side="left")

    def update_force_entry_states(self, event=None):
        """Enable only the force-voltage box needed for the selected test."""
        mode = self.test_select_combo.get()

        if mode == "Input Leakage High only":
            self.high_force_entry.config(state="normal")
            self.low_force_entry.config(state="disabled")
        elif mode == "Input Leakage Low only":
            self.high_force_entry.config(state="disabled")
            self.low_force_entry.config(state="normal")
        else:
            self.high_force_entry.config(state="normal")
            self.low_force_entry.config(state="normal")

    def create_right_panel(self):
        right_frame = ttk.Frame(self.root, padding="10")
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.rowconfigure(0, weight=1)
        right_frame.columnconfigure(0, weight=1)

        columns = (
            "run", "chip", "pin", "test", "forced_v", "avg_ua",
            "min_ua", "max_ua", "limit_ua", "samples", "result"
        )
        self.tree = ttk.Treeview(right_frame, columns=columns, show="headings")

        headings = {
            "run": "Run",
            "chip": "Chip",
            "pin": "Pin",
            "test": "Test",
            "forced_v": "Forced V",
            "avg_ua": "Avg uA",
            "min_ua": "Min uA",
            "max_ua": "Max uA",
            "limit_ua": "Limit uA",
            "samples": "Samples",
            "result": "Result",
        }

        widths = {
            "run": 45, "chip": 80, "pin": 80, "test": 160, "forced_v": 90,
            "avg_ua": 85, "min_ua": 85, "max_ua": 85, "limit_ua": 85,
            "samples": 70, "result": 95,
        }

        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="center")

        self.tree.tag_configure("pass", background="#d4edda")
        self.tree.tag_configure("fail", background="#f8d7da")
        self.tree.tag_configure("info", background="#d1ecf1")

        self.tree.grid(row=0, column=0, sticky="nsew")

        y_scroll = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=y_scroll.set)
        y_scroll.grid(row=0, column=1, sticky="ns")

        x_scroll = ttk.Scrollbar(right_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(xscroll=x_scroll.set)
        x_scroll.grid(row=1, column=0, sticky="ew")

    # ============================================================
    # TEST FLOW
    # ============================================================
    def start_thread(self):
        try:
            self.params = self.get_user_inputs()
        except ValueError as e:
            self.update_status(f"Input Error: {e}", "#f8d7da")
            messagebox.showerror("Input Error", str(e))
            return

        self.start_button.config(state=tk.DISABLED)
        self.clear_button.config(state=tk.DISABLED)
        self.update_status("Status: INITIALIZING PXIe...", "#fff3cd")

        test_thread = threading.Thread(target=self.run_hardware_test, daemon=True)
        test_thread.start()

    def get_user_inputs(self):
        chip_name = self.chip_name_entry.get().strip() or "DUT"
        pin_label = self.pin_label_entry.get().strip()
        if not pin_label:
            raise ValueError("Enter the pin label being tested, for example IN+ or IN-.")

        return {
            "chip_name": chip_name,
            "pin_label": pin_label,
            "vdd": float(self.vdd_entry.get()),
            "vee": float(self.vee_entry.get()),
            "test_mode": self.test_select_combo.get(),
            "high_force_voltage": float(self.high_force_entry.get()),
            "low_force_voltage": float(self.low_force_entry.get()),
            "smu_resource": self.smu_resource_entry.get().strip(),
            "ps_resource": self.ps_resource_entry.get().strip(),
            "ps_pos_channel": self.ps_pos_channel_entry.get().strip(),
            "ps_neg_channel": self.ps_neg_channel_entry.get().strip(),
            "ps_current_limit": float(self.ps_current_limit_entry.get()),
            "smu_current_limit": float(self.smu_current_limit_entry.get()) * 1e-3,  # mA to A
            "leakage_limit": self.get_leakage_limit_amps(),
            "sample_count": int(self.sample_count_entry.get()),
            "dummy_count": int(self.dummy_count_entry.get()),
            "measure_delay": float(self.measure_delay_entry.get()),
            "initial_settle_delay": float(self.initial_settle_entry.get()),
            "supply_settle_delay": float(self.supply_settle_entry.get()),
            "reset": self.reset_var.get(),
        }

    def get_leakage_limit_amps(self):
        """Return user-selected leakage limit converted to amps."""
        value = float(self.leakage_limit_entry.get())
        unit = self.leakage_unit_combo.get()

        if unit == "nA":
            return value * 1e-9
        if unit == "uA":
            return value * 1e-6
        if unit == "mA":
            return value * 1e-3

        raise ValueError("Select a valid leakage limit unit: nA, uA, or mA.")

    def run_hardware_test(self):
        p = self.params
        self.root.after(0, self.update_status, f"Status: TESTING {p['pin_label']} - {p['test_mode']}...", "#fff3cd")

        try:
            results = run_full_leakage_test(
                vdd=p["vdd"],
                vee=p["vee"],
                high_force_voltage=p["high_force_voltage"],
                low_force_voltage=p["low_force_voltage"],
                test_mode=p["test_mode"],
                smu_resource=p["smu_resource"],
                ps_resource=p["ps_resource"],
                ps_pos_channel=p["ps_pos_channel"],
                ps_neg_channel=p["ps_neg_channel"],
                ps_current_limit=p["ps_current_limit"],
                smu_current_limit=p["smu_current_limit"],
                leakage_limit=p["leakage_limit"],
                sample_count=p["sample_count"],
                dummy_count=p["dummy_count"],
                initial_settle_delay=p["initial_settle_delay"],
                measure_delay=p["measure_delay"],
                supply_settle_delay=p["supply_settle_delay"],
                reset=p["reset"],
            )

            if results.get("error"):
                self.root.after(0, self.finish_test, f"Test Error: {results['error']}", "#f8d7da")
                return

            self.root.after(0, self.display_results, results, p)

        except Exception as e:
            self.root.after(0, self.finish_test, f"Error: {e}", "#f8d7da")

    # ============================================================
    # RESULT DISPLAY
    # ============================================================
    def display_results(self, results, p):
        self.run_counter += 1

        power_up = results.get("power_up")
        if power_up:
            for label, key in (("V+ Readback", "vplus"), ("V- Readback", "vminus")):
                rail = power_up.get(key)
                if rail:
                    supply_text = (
                        f"V={rail['measured_voltage_V']:.4f} V, "
                        f"I={rail['measured_current_A'] * 1e3:.4f} mA"
                    )
                    self.tree.insert(
                        "", tk.END,
                        values=(self.run_counter, p["chip_name"], p["pin_label"], label,
                                supply_text, "", "", "", "", "", "INFO"),
                        tags=("info",)
                    )

        high = results.get("input_leakage_high")
        low = results.get("input_leakage_low")

        all_passed = True
        for item in (high, low):
            if item is None:
                continue

            passed = item["status"] == "PASSED"
            all_passed = all_passed and passed
            tag = "pass" if passed else "fail"
            result_text = "PASS" if passed else "FAIL"

            self.tree.insert(
                "", tk.END,
                values=(
                    self.run_counter,
                    p["chip_name"],
                    p["pin_label"],
                    item["test"],
                    f"{item['forced_voltage_V']:.3f}",
                    f"{item['avg_current_uA']:.4f}",
                    f"{item['min_current_uA']:.4f}",
                    f"{item['max_current_uA']:.4f}",
                    f"{item['limit_uA']:.4f}",
                    item["sample_count"],
                    result_text,
                ),
                tags=(tag,)
            )

        if all_passed:
            self.finish_test(f"Status: DONE - {p['pin_label']} PASSED", "#d4edda")
        else:
            self.finish_test(f"Status: DONE - {p['pin_label']} FAILED", "#f8d7da")

    def update_status(self, text, color):
        self.status_label.config(text=text, background=color)

    def finish_test(self, final_text, color):
        self.status_label.config(text=final_text, background=color)
        self.start_button.config(state=tk.NORMAL)
        self.clear_button.config(state=tk.NORMAL)

    def clear_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.run_counter = 0
        self.update_status("Status: READY", "#d4edda")


if __name__ == "__main__":
    root = tk.Tk()
    app = LeakageTestGUI(root)
    root.mainloop()
