import tkinter as tk
from tkinter import ttk
import threading
import time
import random

class LeakageTestGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Leakage Test Interface")
        self.root.geometry("700x550")
        
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.create_left_panel()
        self.create_right_panel()

    def create_left_panel(self):
        left_frame = ttk.Frame(self.root, padding="10")
        left_frame.grid(row=0, column=0, sticky="nsew")

        description_text = (
            "This test forces a specified DC voltage on each target pin and measures the "
            "resulting steady-state current. The pin passes if the absolute measured "
            "current remains below the defined maximum leakage threshold. To account for "
            "parasitic capacitive charging, measurements are recorded only after a "
            "predefined settling time and averaged. Vdd and Gnd pins are excluded."
        )
        desc_label = ttk.Label(left_frame, text=description_text, wraplength=300, justify="left")
        desc_label.pack(fill="x", pady=(0, 15))

        # --- DUT Specifications ---
        lf_dut = ttk.LabelFrame(left_frame, text="DUT Specifications", padding="10")
        lf_dut.pack(fill="x", pady=(0, 10))

        ttk.Label(lf_dut, text="Chip name:").grid(row=0, column=0, sticky="w", pady=2)
        self.chip_name_entry = ttk.Entry(lf_dut)
        self.chip_name_entry.grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(lf_dut, text="Total Pins:").grid(row=1, column=0, sticky="w", pady=2)
        self.pins_spinbox = ttk.Spinbox(lf_dut, from_=1, to=100, width=5)
        self.pins_spinbox.grid(row=1, column=1, sticky="w", pady=2)
        self.pins_spinbox.set(4)

        ttk.Label(lf_dut, text="Vdd pin:").grid(row=2, column=0, sticky="w", pady=2)
        self.vdd_spinbox = ttk.Spinbox(lf_dut, from_=1, to=100, width=5)
        self.vdd_spinbox.grid(row=2, column=1, sticky="w", pady=2)
        self.vdd_spinbox.set(1)

        ttk.Label(lf_dut, text="Gnd pin:").grid(row=3, column=0, sticky="w", pady=2)
        self.gnd_spinbox = ttk.Spinbox(lf_dut, from_=1, to=100, width=5)
        self.gnd_spinbox.grid(row=3, column=1, sticky="w", pady=2)
        self.gnd_spinbox.set(2)

        # --- Test Conditions ---
        lf_test = ttk.LabelFrame(left_frame, text="Test Conditions", padding="10")
        lf_test.pack(fill="x", pady=(0, 10))

        ttk.Label(lf_test, text="Forced Voltage (V):").grid(row=0, column=0, sticky="w", pady=2)
        self.voltage_entry = ttk.Entry(lf_test, width=10)
        self.voltage_entry.grid(row=0, column=1, sticky="w", pady=2)
        self.voltage_entry.insert(0, "3.3")

        ttk.Label(lf_test, text="Max Leakage (nA):").grid(row=1, column=0, sticky="w", pady=2)
        self.leakage_entry = ttk.Entry(lf_test, width=10)
        self.leakage_entry.grid(row=1, column=1, sticky="w", pady=2)
        self.leakage_entry.insert(0, "100")

        # --- Status and Controls ---
        # Defaulting to a pleasant, reassuring green for "READY"
        self.status_label = ttk.Label(left_frame, text="Status: READY", background="#d4edda", padding=5, anchor="center")
        self.status_label.pack(fill="x", pady=(10, 10))

        self.start_button = ttk.Button(left_frame, text="Start Leakage Test", command=self.start_thread)
        self.start_button.pack(pady=5)

    def create_right_panel(self):
        right_frame = ttk.Frame(self.root, padding="10")
        right_frame.grid(row=0, column=1, sticky="nsew")

        columns = ("pin", "current", "result")
        self.tree = ttk.Treeview(right_frame, columns=columns, show="headings")
        self.tree.heading("pin", text="Pin")
        self.tree.heading("current", text="Current (nA)")
        self.tree.heading("result", text="Result")
        
        self.tree.column("pin", width=50, anchor="center")
        self.tree.column("current", width=100, anchor="center")
        self.tree.column("result", width=80, anchor="center")
        
        # --- The Color Tags ---
        # We configure two tags that will dictate the background color of the rows
        self.tree.tag_configure('pass', background='#d4edda') # Light Green
        self.tree.tag_configure('fail', background='#f8d7da') # Light Red
        
        self.tree.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

    def start_thread(self):
        self.start_button.config(state=tk.DISABLED)
        # Yellow for "working on it"
        self.status_label.config(text="Status: INITIALIZING PXIe...", background="#fffacd")
        
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        test_thread = threading.Thread(target=self.run_hardware_test, daemon=True)
        test_thread.start()

    def run_hardware_test(self):
        try:
            total_pins = int(self.pins_spinbox.get())
            vdd_pin = int(self.vdd_spinbox.get())
            gnd_pin = int(self.gnd_spinbox.get())
            max_leakage = float(self.leakage_entry.get())
            
            pins_to_test = [p for p in range(1, total_pins + 1) if p not in (vdd_pin, gnd_pin)]
            
            for pin in pins_to_test:
                self.root.after(0, self.update_status, f"Status: TESTING PIN {pin}...", "#fffacd")
                
                time.sleep(0.8) 
                
                measured_current = random.uniform(1.0, 150.0)
                
                # Determine result and the corresponding tag
                if measured_current <= max_leakage:
                    result_text = "PASS"
                    row_tag = "pass"
                else:
                    result_text = "FAIL"
                    row_tag = "fail"
                
                self.root.after(0, self.insert_result, pin, f"{measured_current:.2f}", result_text, row_tag)
                
            # Back to Green when finished successfully
            self.root.after(0, self.finish_test, "Status: DONE", "#d4edda")
            
        except Exception as e:
            # Harsh Red if the code breaks or user inputs letters instead of numbers
            self.root.after(0, self.finish_test, f"Error: {str(e)}", "#f8d7da")

    def update_status(self, text, color):
        self.status_label.config(text=text, background=color)

    def insert_result(self, pin, current, result, tag):
        # The 'tags' parameter applies the color configuration we set earlier
        self.tree.insert("", tk.END, values=(pin, current, result), tags=(tag,))

    def finish_test(self, final_text, color):
        self.status_label.config(text=final_text, background=color)
        self.start_button.config(state=tk.NORMAL)

if __name__ == "__main__":
    root = tk.Tk()
    app = LeakageTestGUI(root)
    root.mainloop()