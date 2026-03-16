from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QDoubleSpinBox, QComboBox, QTableWidget, QTableWidgetItem, QSpinBox
)
from PySide6.QtCore import Qt
from qtutils import inmain_later
import threading
import time


# ------------------------------
# Worker thread function
# ------------------------------
def long_task(callback, passfail_callback, table_callback, params, stop_flag):
    pin_count = params["Input pins"]
    vdd = int(params["Vdd pin"])
    gnd = int(params["Gnd pin"])

    vlow = params["Vlow (V)"]
    vhigh = params["Vhigh (V)"]

    # Build list of test pins (exclude Vdd and Gnd)
    test_pins = [p for p in range(1, pin_count + 1) if p not in (vdd, gnd)]

    overall_pass = True

    for row_index, pin in enumerate(test_pins):

        if stop_flag["stop"]:
            inmain_later(callback, "Stopped")
            inmain_later(passfail_callback, "FAIL")
            return

        time.sleep(0.4)

        # Generate arbitrary fake voltage
        voltage = round(0.5 + 0.05 * pin, 3)  # example formula

        # Update table with voltage
        inmain_later(table_callback, row_index, f"{voltage} V")

        # Check pass/fail
        if not (vlow <= voltage <= vhigh):
            overall_pass = False

    # Final result
    inmain_later(passfail_callback, "PASS" if overall_pass else "FAIL")
    inmain_later(callback, "Done!")

# ------------------------------
# Main GUI Window
# ------------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Continuity Test GUI")
        self.resize(600, 550)

        self.running = False
        self.stop_flag = {"stop": False}

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)

        # --------------------------
        # DUT SPECIFICATIONS SECTION
        # --------------------------
        
        dut_label = QLabel("<b>DUT Specifications</b>")
        dut_label.setContentsMargins(0, 10, 0, 5)
        form.addRow(dut_label)

        # 1. Chip name
        self.chip_name = QLineEdit()
        form.addRow("Chip name:", self.chip_name)

        # 2. Pins (minimum 4)
        self.pins = QSpinBox()
        self.pins.setRange(4, 12)
        form.addRow("Pins:", self.pins)

        # 3. Vdd pin
        self.vdd_pin = QComboBox()
        form.addRow("Vdd pin:", self.vdd_pin)

        # 4. Gnd pin
        self.gnd_pin = QComboBox()
        form.addRow("Gnd pin:", self.gnd_pin)

        # --------------------------
        # RIGHT SIDE: RESULTS TABLE
        # --------------------------
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Pin", "Result"])

        # Connect AFTER table exists
        self.pins.valueChanged.connect(self.update_pin_choices)
        self.vdd_pin.currentIndexChanged.connect(self.update_pin_choices)
        self.gnd_pin.currentIndexChanged.connect(self.update_pin_choices)

        # Initialize dropdowns and table
        self.update_pin_choices()

        # --------------------------
        # TEST CONDITIONS SECTION
        # --------------------------
        test_label = QLabel("<b>Test Conditions</b>")
        test_label.setContentsMargins(0, 15, 0, 5)
        form.addRow(test_label)

        # 5. Max current
        self.max_current = QDoubleSpinBox()
        self.max_current.setRange(1, 10)
        self.max_current.setSuffix(" mA")
        form.addRow("Max current:", self.max_current)

        # 6. Vlow + Vhigh
        vrange_layout = QHBoxLayout()
        self.vlow = QDoubleSpinBox()
        self.vlow.setRange(0, 1)
        self.vlow.setSuffix(" V")
        self.vhigh = QDoubleSpinBox()
        self.vhigh.setRange(0, 1)
        self.vhigh.setSuffix(" V")
        vrange_layout.addWidget(QLabel("Vlow:"))
        vrange_layout.addWidget(self.vlow)
        vrange_layout.addWidget(QLabel("Vhigh:"))
        vrange_layout.addWidget(self.vhigh)
        form.addRow("Voltage range:", vrange_layout)
        self.vlow.setValue(0.55)
        self.vhigh.setValue(0.75)

        # PASS/FAIL
        self.passfail_label = QLabel("READY")
        self.passfail_label.setStyleSheet("background-color: lightgray; padding: 6px;")
        form.addRow("Result:", self.passfail_label)

        # Status label
        self.label = QLabel("Ready")

        # Start/Stop button
        self.button = QPushButton("Start")
        self.button.clicked.connect(self.start_or_stop)

        # --------------------------
        # TEST DESCRIPTION NOTE
        # --------------------------
        # Left layout
        left_layout = QVBoxLayout()
        
        self.subtitle = QLabel("<b>Continuity Test</b>")
        self.subtitle.setStyleSheet("font-size: 14px;")
        self.subtitle.setContentsMargins(0, 0, 0, 5)
        left_layout.addWidget(self.subtitle)
        self.description = QLabel(
            "This test measures per-pin voltages for a given forced current until " \
            "the specified voltage range is met. Result voltage is averaged " \
            "using 30 samples. Vdd and Gnd pins are excluded from testing."
        )
        self.description.setStyleSheet("font-size: 12px; color: #333;")
        self.description.setWordWrap(True)
        left_layout.addWidget(self.description)

        left_layout.addLayout(form)
        left_layout.addWidget(self.label)
        left_layout.addWidget(self.button)

        # --------------------------
        # MAIN LAYOUT (Center + RIGHT)
        # --------------------------
        main_layout = QHBoxLayout()
        main_layout.addLayout(left_layout, 1)
        main_layout.addWidget(self.table, 1)

        self.setLayout(main_layout)

    # ------------------------------
    # Update Vdd/Gnd dropdowns AND table
    # ------------------------------
    def update_pin_choices(self):
        count = int(self.pins.value())

        # Save current selections
        old_vdd = self.vdd_pin.currentText()
        old_gnd = self.gnd_pin.currentText()

        # Rebuild dropdowns
        self.vdd_pin.blockSignals(True)
        self.gnd_pin.blockSignals(True)

        self.vdd_pin.clear()
        self.gnd_pin.clear()

        for i in range(1, count + 1):
            self.vdd_pin.addItem(str(i))
            self.gnd_pin.addItem(str(i))

        # Restore selections if still valid
        if old_vdd in [str(i) for i in range(1, count + 1)]:
            self.vdd_pin.setCurrentText(old_vdd)
        if old_gnd in [str(i) for i in range(1, count + 1)]:
            self.gnd_pin.setCurrentText(old_gnd)

        # Ensure Vdd != Gnd
        if self.vdd_pin.currentText() == self.gnd_pin.currentText():
            # Move Gnd to next available pin
            idx = (self.vdd_pin.currentIndex() + 1) % count
            self.gnd_pin.setCurrentIndex(idx)

        self.vdd_pin.blockSignals(False)
        self.gnd_pin.blockSignals(False)

        # Update table
        self.update_table_rows()

    # ------------------------------
    # Update table row count (exclude Vdd/Gnd)
    # ------------------------------
    def update_table_rows(self):
        count = int(self.pins.value())
        vdd = int(self.vdd_pin.currentText())
        gnd = int(self.gnd_pin.currentText())

        test_pins = [p for p in range(1, count + 1) if p not in (vdd, gnd)]

        self.table.setRowCount(len(test_pins))

        for row, pin in enumerate(test_pins):
            self.table.setItem(row, 0, QTableWidgetItem(str(pin)))
            self.table.setItem(row, 1, QTableWidgetItem("—"))

    # ------------------------------
    # Update a single table row
    # ------------------------------
    def update_table_result(self, row, result):
        self.table.setItem(row, 1, QTableWidgetItem(result))

    # ------------------------------
    # Collect parameters
    # ------------------------------
    def collect_parameters(self):
        return {
            "Input pins": int(self.pins.value()),
            "Vdd pin": self.vdd_pin.currentText(),
            "Gnd pin": self.gnd_pin.currentText(),
            "Max current (mA)": self.max_current.value(),
            "Vlow (V)": self.vlow.value(),
            "Vhigh (V)": self.vhigh.value(),
            "Chip name": self.chip_name.text(),
        }

    # ------------------------------
    # Start/Stop logic
    # ------------------------------
    def start_or_stop(self):
        if not self.running:
            self.start_task()
        else:
            self.stop_flag["stop"] = True
            self.button.setText("Stopping...")

    # ------------------------------
    # Start worker thread
    # ------------------------------
    def start_task(self):
        self.running = True
        self.stop_flag["stop"] = False

        self.button.setText("Stop")
        self.passfail_label.setText("RUNNING")
        self.passfail_label.setStyleSheet("background-color: yellow; padding: 6px;")

        # Clear table when starting test
        self.update_table_rows()

        params = self.collect_parameters()
        self.label.setText("Working...")

        threading.Thread(
            target=long_task,
            args=(self.update_label, self.update_passfail, self.update_table_result, params, self.stop_flag),
            daemon=True
        ).start()

    # ------------------------------
    # GUI update callback
    # ------------------------------
    def update_label(self, text):
        self.label.setText(text)

        if text in ("Done!", "Stopped"):
            self.running = False
            self.button.setText("Start")


    # ------------------------------
    # Pass/Fail update callback
    # ------------------------------
    def update_passfail(self, result):
        if result == "PASS":
            self.passfail_label.setText("PASS")
            self.passfail_label.setStyleSheet("background-color: lightgreen; padding: 6px;")
        elif result == "FAIL":
            self.passfail_label.setText("FAIL")
            self.passfail_label.setStyleSheet("background-color: red; color: white; padding: 6px;")
        else:
            self.passfail_label.setText("READY")
            self.passfail_label.setStyleSheet("background-color: lightgray; padding: 6px;")

# ------------------------------
# Run the application
# ------------------------------
if __name__ == "__main__":
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
