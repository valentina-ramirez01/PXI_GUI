import tkinter as tk
from tkinter import ttk
import threading
import time
import random


class PowerSupplyCurrentGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Power Supply Current Test Interface")
        self.root.geometry("760x620")

        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.create_left_panel()
        self.create_right_panel()

    def create_left_panel(self):
        left_frame = ttk.Frame(self.root, padding="10")
        left_frame.grid(row=0, column=0, sticky="nsew")

        description_text = (
            "This test applies the positive and negative supply voltages to the DUT "
            "and measures the current drawn from each power supply rail. The device "
            "passes if the measured supply currents stay below the maximum allowed limits."
        )

        desc_label = ttk.Label(
            left_frame,
            text=description_text,
            wraplength=320,
            justify="left"
        )
        desc_label.pack(fill="x", pady=(0, 15))

        # --- DUT Specifications ---
        lf_dut = ttk.LabelFrame(left_frame, text="DUT Specifications", padding="10")
        lf_dut.pack(fill="x", pady=(0, 10))

        ttk.Label(lf_dut, text="Chip name:").grid(row=0, column=0, sticky="w", pady=2)
        self.chip_name_entry = ttk.Entry(lf_dut)
        self.chip_name_entry.grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(lf_dut, text="+V Supply Pin:").grid(row=1, column=0, sticky="w", pady=2)
        self.pos_supply_pin_spinbox = ttk.Spinbox(lf_dut, from_=1, to=100, width=5)
        self.pos_supply_pin_spinbox.grid(row=1, column=1, sticky="w", pady=2)
        self.pos_supply_pin_spinbox.set(1)

        ttk.Label(lf_dut, text="-V Supply Pin:").grid(row=2, column=0, sticky="w", pady=2)
        self.neg_supply_pin_spinbox = ttk.Spinbox(lf_dut, from_=1, to=100, width=5)
        self.neg_supply_pin_spinbox.grid(row=2, column=1, sticky="w", pady=2)
        self.neg_supply_pin_spinbox.set(2)

        ttk.Label(lf_dut, text="IN+ Pin:").grid(row=3, column=0, sticky="w", pady=2)
        self.in_pos_pin_spinbox = ttk.Spinbox(lf_dut, from_=1, to=100, width=5)
        self.in_pos_pin_spinbox.grid(row=3, column=1, sticky="w", pady=2)
        self.in_pos_pin_spinbox.set(3)

        ttk.Label(lf_dut, text="IN- Pin:").grid(row=4, column=0, sticky="w", pady=2)
        self.in_neg_pin_spinbox = ttk.Spinbox(lf_dut, from_=1, to=100, width=5)
        self.in_neg_pin_spinbox.grid(row=4, column=1, sticky="w", pady=2)
        self.in_neg_pin_spinbox.set(4)

        lf_dut.columnconfigure(1, weight=1)

        # --- Test Conditions ---
        lf_test = ttk.LabelFrame(left_frame, text="Test Conditions", padding="10")
        lf_test.pack(fill="x", pady=(0, 10))

        ttk.Label(lf_test, text="+V Supply (V):").grid(row=0, column=0, sticky="w", pady=2)
        self.pos_voltage_entry = ttk.Entry(lf_test, width=10)
        self.pos_voltage_entry.grid(row=0, column=1, sticky="w", pady=2)
        self.pos_voltage_entry.insert(0, "5.0")

        ttk.Label(lf_test, text="-V Supply (V):").grid(row=1, column=0, sticky="w", pady=2)
        self.neg_voltage_entry = ttk.Entry(lf_test, width=10)
        self.neg_voltage_entry.grid(row=1, column=1, sticky="w", pady=2)
        self.neg_voltage_entry.insert(0, "-5.0")

        ttk.Label(lf_test, text="IN+ Voltage (V):").grid(row=2, column=0, sticky="w", pady=2)
        self.in_pos_voltage_entry = ttk.Entry(lf_test, width=10)
        self.in_pos_voltage_entry.grid(row=2, column=1, sticky="w", pady=2)
        self.in_pos_voltage_entry.insert(0, "0.0")

        ttk.Label(lf_test, text="IN- Voltage (V):").grid(row=3, column=0, sticky="w", pady=2)
        self.in_neg_voltage_entry = ttk.Entry(lf_test, width=10)
        self.in_neg_voltage_entry.grid(row=3, column=1, sticky="w", pady=2)
        self.in_neg_voltage_entry.insert(0, "0.0")

        ttk.Label(lf_test, text="Max +V Current (mA):").grid(row=4, column=0, sticky="w", pady=2)
        self.max_pos_current_entry = ttk.Entry(lf_test, width=10)
        self.max_pos_current_entry.grid(row=4, column=1, sticky="w", pady=2)
        self.max_pos_current_entry.insert(0, "20")

        ttk.Label(lf_test, text="Max -V Current (mA):").grid(row=5, column=0, sticky="w", pady=2)
        self.max_neg_current_entry = ttk.Entry(lf_test, width=10)
        self.max_neg_current_entry.grid(row=5, column=1, sticky="w", pady=2)
        self.max_neg_current_entry.insert(0, "20")

        # --- Status and Controls ---
        self.status_label = ttk.Label(
            left_frame,
            text="Status: READY",
            background="#d4edda",
            padding=5,
            anchor="center"
        )
        self.status_label.pack(fill="x", pady=(10, 10))

        self.start_button = ttk.Button(
            left_frame,
            text="Start Supply Current Test",
            command=self.start_thread
        )
        self.start_button.pack(pady=5)

    def create_right_panel(self):
        right_frame = ttk.Frame(self.root, padding="10")
        right_frame.grid(row=0, column=1, sticky="nsew")

        columns = ("rail", "pin", "voltage", "current", "result")
        self.tree = ttk.Treeview(right_frame, columns=columns, show="headings")

        self.tree.heading("rail", text="Rail")
        self.tree.heading("pin", text="Pin")
        self.tree.heading("voltage", text="Voltage (V)")
        self.tree.heading("current", text="Current (mA)")
        self.tree.heading("result", text="Result")

        self.tree.column("rail", width=80, anchor="center")
        self.tree.column("pin", width=60, anchor="center")
        self.tree.column("voltage", width=90, anchor="center")
        self.tree.column("current", width=100, anchor="center")
        self.tree.column("result", width=80, anchor="center")

        self.tree.tag_configure("pass", background="#d4edda")
        self.tree.tag_configure("fail", background="#f8d7da")

        self.tree.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

    def start_thread(self):
        self.start_button.config(state=tk.DISABLED)
        self.status_label.config(text="Status: INITIALIZING PXIe...", background="#fffacd")

        for item in self.tree.get_children():
            self.tree.delete(item)

        test_thread = threading.Thread(target=self.run_hardware_test, daemon=True)
        test_thread.start()

    def run_hardware_test(self):
        try:
            pos_pin = int(self.pos_supply_pin_spinbox.get())
            neg_pin = int(self.neg_supply_pin_spinbox.get())
            in_pos_pin = int(self.in_pos_pin_spinbox.get())
            in_neg_pin = int(self.in_neg_pin_spinbox.get())

            pos_voltage = float(self.pos_voltage_entry.get())
            neg_voltage = float(self.neg_voltage_entry.get())
            in_pos_voltage = float(self.in_pos_voltage_entry.get())
            in_neg_voltage = float(self.in_neg_voltage_entry.get())

            max_pos_current = float(self.max_pos_current_entry.get())
            max_neg_current = float(self.max_neg_current_entry.get())

            self.root.after(
                0,
                self.update_status,
                "Status: APPLYING POWER SUPPLIES AND INPUT CONDITIONS...",
                "#fffacd"
            )

            # Replace with real PXIe setup later:
            # Apply +V to pos_pin
            # Apply -V to neg_pin
            # Apply IN+ voltage to in_pos_pin
            # Apply IN- voltage to in_neg_pin
            time.sleep(0.8)

            self.root.after(
                0,
                self.update_status,
                "Status: MEASURING SUPPLY CURRENTS...",
                "#fffacd"
            )

            # Simulated measurements
            measured_pos_current = random.uniform(1.0, 30.0)
            measured_neg_current = random.uniform(1.0, 30.0)

            self.evaluate_and_insert("+V", pos_pin, pos_voltage, measured_pos_current, max_pos_current)
            self.evaluate_and_insert("-V", neg_pin, neg_voltage, measured_neg_current, max_neg_current)

        

            self.root.after(0, self.finish_test, "Status: DONE", "#d4edda")

        except Exception as e:
            self.root.after(0, self.finish_test, f"Error: {str(e)}", "#f8d7da")

    def evaluate_and_insert(self, rail, pin, voltage, measured_current, max_current):
        if measured_current <= max_current:
            result_text = "PASS"
            row_tag = "pass"
        else:
            result_text = "FAIL"
            row_tag = "fail"

        self.root.after(
            0,
            self.insert_result,
            rail,
            pin,
            f"{voltage:.2f}",
            f"{measured_current:.3f}",
            result_text,
            row_tag
        )

    def insert_operation_mode_row(self, input_name, pin, voltage):
        self.root.after(
            0,
            self.insert_result,
            input_name,
            pin,
            f"{voltage:.2f}",
            "N/A",
            "SET",
            ""
        )

    def update_status(self, text, color):
        self.status_label.config(text=text, background=color)

    def insert_result(self, rail, pin, voltage, current, result, tag):
        self.tree.insert("", tk.END, values=(rail, pin, voltage, current, result), tags=(tag,))

    def finish_test(self, final_text, color):
        self.status_label.config(text=final_text, background=color)
        self.start_button.config(state=tk.NORMAL)


if __name__ == "__main__":
    root = tk.Tk()
    app = PowerSupplyCurrentGUI(root)
    root.mainloop()