
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QDoubleSpinBox, QComboBox, QTableWidget, QTableWidgetItem, QSpinBox
)
from PySide6.QtCore import Qt
from qtutils import inmain_later
import threading

import continuity_test as ct


def parse_pin_list(pin_text, pin_count, excluded_pins=None):
    """
    Parse user-entered pin list like:
    "1,3,5-8"
    Returns sorted unique pins excluding excluded_pins.
    Blank = all pins except excluded pins.
    """
    excluded = set(excluded_pins or [])
    pin_text = (pin_text or "").strip()

    if not pin_text:
        return [p for p in range(1, pin_count + 1) if p not in excluded]

    pins = set()

    for part in pin_text.split(","):
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            pieces = part.split("-", 1)
            if len(pieces) != 2:
                raise ValueError(f"Invalid range: {part}")

            start = int(pieces[0].strip())
            end = int(pieces[1].strip())

            if start > end:
                raise ValueError(f"Invalid range: {part}")

            for p in range(start, end + 1):
                if not (1 <= p <= pin_count):
                    raise ValueError(f"Pin out of range: {p}")
                if p not in excluded:
                    pins.add(p)
        else:
            p = int(part)
            if not (1 <= p <= pin_count):
                raise ValueError(f"Pin out of range: {p}")
            if p not in excluded:
                pins.add(p)

    return sorted(pins)


def format_one_sweep(tag, result):
    if result is None:
        return f"{tag}: no data"

    if result.get("status") == "PASS":
        avg_v = result.get("avg_voltage_V")
        current_ma = result.get("current_to_target_mA")
        return f"{tag}: {avg_v:.4f} V @ {current_ma:.4f} mA"

    reason = result.get("reason", "unknown failure")
    return f"{tag}: FAIL ({reason})"


def long_task(callback, passfail_callback, table_callback, params, stop_flag):
    selected_pin = params["Selected test pin"]

    if selected_pin is None:
        inmain_later(callback, "No test pin selected")
        inmain_later(passfail_callback, "FAIL")
        return

    if stop_flag["stop"]:
        inmain_later(callback, "Stopped")
        inmain_later(passfail_callback, "FAIL")
        return

    pin_label = f"Pin {selected_pin}"
    inmain_later(callback, f"Testing {pin_label}...")

    try:
        results = ct.run_full_diode_sweep_test(
            input_pin=pin_label,
            smu_resource=params["SMU Resource"],
            reset=True,
            current_start=params["Current start (A)"],
            current_stop=params["Current stop (A)"],
            current_points=params["Current points"],
            sample_count=params["Sample count"],
            settle_delay=params["Settle delay (s)"],
            forward_min=params["Vlow (V)"],
            forward_max=params["Vhigh (V)"],
            reverse_min=-params["Vhigh (V)"],
            reverse_max=-params["Vlow (V)"],
        )

        if results.get("error"):
            inmain_later(table_callback, selected_pin, "FAIL", f"ERROR: {results['error']}")
            inmain_later(passfail_callback, "FAIL")
            inmain_later(callback, "Done! Reconnect the next pin and run again.")
            return

        forward = results.get("forward_sweep")
        reverse = results.get("reverse_sweep")

        row_pass = (
            forward is not None and reverse is not None and
            forward.get("status") == "PASS" and
            reverse.get("status") == "PASS"
        )

        status_text = "PASS" if row_pass else "FAIL"
        details_text = f"{format_one_sweep('FWD', forward)} | {format_one_sweep('REV', reverse)}"

        inmain_later(table_callback, selected_pin, status_text, details_text)
        inmain_later(passfail_callback, status_text)
        inmain_later(callback, "Done! Reconnect the next pin and run again.")

    except Exception as exc:
        inmain_later(table_callback, selected_pin, "FAIL", f"ERROR: {exc}")
        inmain_later(passfail_callback, "FAIL")
        inmain_later(callback, "Stopped due to error")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Continuity Test GUI")
        self.resize(1080, 650)

        self.running = False
        self.stop_flag = {"stop": False}
        self.result_history = {}

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)

        dut_label = QLabel("<b>DUT Specifications</b>")
        dut_label.setContentsMargins(0, 10, 0, 5)
        form.addRow(dut_label)

        self.chip_name = QLineEdit()
        form.addRow("Chip name:", self.chip_name)

        self.pins = QSpinBox()
        self.pins.setRange(4, 128)
        self.pins.setValue(8)
        form.addRow("Pins:", self.pins)

        self.vdd_pin = QComboBox()
        form.addRow("Vdd pin:", self.vdd_pin)

        self.gnd_pin = QComboBox()
        form.addRow("Gnd pin:", self.gnd_pin)

        self.test_pins_input = QLineEdit()
        self.test_pins_input.setPlaceholderText("Example: 1,3,5-8  (blank = all except Vdd/Gnd)")
        form.addRow("Pins available:", self.test_pins_input)

        self.selected_test_pin = QComboBox()
        form.addRow("Pin to test now:", self.selected_test_pin)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Pin", "Status", "Details"])
        self.table.horizontalHeader().setStretchLastSection(True)

        self.pins.valueChanged.connect(self.update_pin_choices)
        self.vdd_pin.currentIndexChanged.connect(self.update_pin_choices)
        self.gnd_pin.currentIndexChanged.connect(self.update_pin_choices)
        self.test_pins_input.textChanged.connect(self.update_table_rows)

        self.update_pin_choices()

        test_label = QLabel("<b>Test Conditions</b>")
        test_label.setContentsMargins(0, 15, 0, 5)
        form.addRow(test_label)

        self.smu_resource = QLineEdit()
        self.smu_resource.setText(ct.SMU_RESOURCE)
        form.addRow("SMU resource:", self.smu_resource)

        self.max_current = QDoubleSpinBox()
        self.max_current.setRange(0.001, 50.0)
        self.max_current.setDecimals(4)
        self.max_current.setValue(ct.CURRENT_STOP * 1e3)
        self.max_current.setSuffix(" mA")
        form.addRow("Max current:", self.max_current)

        vrange_layout = QHBoxLayout()
        self.vlow = QDoubleSpinBox()
        self.vlow.setRange(0.0, 5.0)
        self.vlow.setDecimals(4)
        self.vlow.setSuffix(" V")
        self.vlow.setValue(ct.FORWARD_VOLTAGE_MIN)

        self.vhigh = QDoubleSpinBox()
        self.vhigh.setRange(0.0, 5.0)
        self.vhigh.setDecimals(4)
        self.vhigh.setSuffix(" V")
        self.vhigh.setValue(ct.FORWARD_VOLTAGE_MAX)

        vrange_layout.addWidget(QLabel("Vlow:"))
        vrange_layout.addWidget(self.vlow)
        vrange_layout.addWidget(QLabel("Vhigh:"))
        vrange_layout.addWidget(self.vhigh)
        form.addRow("Voltage range:", vrange_layout)

        self.current_start = QDoubleSpinBox()
        self.current_start.setDecimals(9)
        self.current_start.setRange(1e-9, 1.0)
        self.current_start.setValue(ct.CURRENT_START)
        self.current_start.setSingleStep(1e-6)
        form.addRow("Current start (A):", self.current_start)

        self.current_points = QSpinBox()
        self.current_points.setRange(2, 500)
        self.current_points.setValue(ct.CURRENT_POINTS)
        form.addRow("Current points:", self.current_points)

        self.sample_count = QSpinBox()
        self.sample_count.setRange(1, 1000)
        self.sample_count.setValue(ct.SAMPLE_COUNT)
        form.addRow("Sample count:", self.sample_count)

        self.settle_delay = QDoubleSpinBox()
        self.settle_delay.setDecimals(4)
        self.settle_delay.setRange(0.0, 10.0)
        self.settle_delay.setValue(ct.SETTLE_DELAY)
        self.settle_delay.setSuffix(" s")
        form.addRow("Settle delay:", self.settle_delay)

        self.passfail_label = QLabel("READY")
        self.passfail_label.setStyleSheet("background-color: lightgray; padding: 6px;")
        form.addRow("Overall result:", self.passfail_label)

        self.label = QLabel("Ready")

        self.button = QPushButton("Start")
        self.button.clicked.connect(self.start_or_stop)

        left_layout = QVBoxLayout()

        self.subtitle = QLabel("<b>Continuity Test</b>")
        self.subtitle.setStyleSheet("font-size: 14px;")
        self.subtitle.setContentsMargins(0, 0, 0, 5)
        left_layout.addWidget(self.subtitle)

        self.description = QLabel(
            "The user can define which DUT pins are valid for continuity testing using a list like 1,3,5-8. "
            "The test runs one pin at a time, then stops so the user can change the physical connection "
            "to the next pin and run again. Results are kept in the history table."
        )
        self.description.setStyleSheet("font-size: 12px; color: #333;")
        self.description.setWordWrap(True)
        left_layout.addWidget(self.description)

        left_layout.addLayout(form)
        left_layout.addWidget(self.label)
        left_layout.addWidget(self.button)

        main_layout = QHBoxLayout()
        main_layout.addLayout(left_layout, 1)
        main_layout.addWidget(self.table, 1.5)

        self.setLayout(main_layout)

    def update_pin_choices(self):
        count = int(self.pins.value())

        old_vdd = self.vdd_pin.currentText()
        old_gnd = self.gnd_pin.currentText()

        self.vdd_pin.blockSignals(True)
        self.gnd_pin.blockSignals(True)

        self.vdd_pin.clear()
        self.gnd_pin.clear()

        for i in range(1, count + 1):
            self.vdd_pin.addItem(str(i))
            self.gnd_pin.addItem(str(i))

        valid_choices = [str(i) for i in range(1, count + 1)]

        if old_vdd in valid_choices:
            self.vdd_pin.setCurrentText(old_vdd)
        else:
            self.vdd_pin.setCurrentIndex(0)

        if old_gnd in valid_choices:
            self.gnd_pin.setCurrentText(old_gnd)
        else:
            self.gnd_pin.setCurrentIndex(1 if count > 1 else 0)

        if self.vdd_pin.currentText() == self.gnd_pin.currentText():
            idx = (self.vdd_pin.currentIndex() + 1) % count
            self.gnd_pin.setCurrentIndex(idx)

        self.vdd_pin.blockSignals(False)
        self.gnd_pin.blockSignals(False)

        self.update_table_rows()

    def update_table_rows(self):
        count = int(self.pins.value())
        vdd = int(self.vdd_pin.currentText())
        gnd = int(self.gnd_pin.currentText())

        current_selection = self.selected_test_pin.currentText() if hasattr(self, "selected_test_pin") else ""

        try:
            test_pins = parse_pin_list(
                self.test_pins_input.text(),
                pin_count=count,
                excluded_pins={vdd, gnd}
            )
        except Exception:
            test_pins = []

        self.selected_test_pin.blockSignals(True)
        self.selected_test_pin.clear()
        for pin in test_pins:
            self.selected_test_pin.addItem(str(pin))

        if current_selection in [str(p) for p in test_pins]:
            self.selected_test_pin.setCurrentText(current_selection)

        self.selected_test_pin.blockSignals(False)

        self.refresh_history_table()

    def update_history_row(self, pin, status, details):
        pin = str(pin)
        self.result_history[pin] = {"status": status, "details": details}
        self.refresh_history_table()

    def refresh_history_table(self):
        sorted_pins = sorted(self.result_history.keys(), key=lambda x: int(x))
        self.table.setRowCount(len(sorted_pins))

        for row, pin_text in enumerate(sorted_pins):
            record = self.result_history[pin_text]

            pin_item = QTableWidgetItem(pin_text)
            status_item = QTableWidgetItem(record["status"])
            details_item = QTableWidgetItem(record["details"])

            if record["status"] == "PASS":
                status_item.setBackground(Qt.green)
            elif record["status"] == "FAIL":
                status_item.setBackground(Qt.red)
                status_item.setForeground(Qt.white)
            elif record["status"] == "RUNNING":
                status_item.setBackground(Qt.lightGray)

            self.table.setItem(row, 0, pin_item)
            self.table.setItem(row, 1, status_item)
            self.table.setItem(row, 2, details_item)

    def update_table_result(self, pin, status, details):
        self.update_history_row(pin, status, details)

    def collect_parameters(self):
        current_stop_a = self.max_current.value() * 1e-3

        selected_pin_text = self.selected_test_pin.currentText().strip()
        selected_pin = int(selected_pin_text) if selected_pin_text else None

        return {
            "Input pins": int(self.pins.value()),
            "Vdd pin": self.vdd_pin.currentText(),
            "Gnd pin": self.gnd_pin.currentText(),
            "Selected test pin": selected_pin,
            "Max current (mA)": self.max_current.value(),
            "Current start (A)": self.current_start.value(),
            "Current stop (A)": current_stop_a,
            "Current points": int(self.current_points.value()),
            "Sample count": int(self.sample_count.value()),
            "Settle delay (s)": self.settle_delay.value(),
            "Vlow (V)": self.vlow.value(),
            "Vhigh (V)": self.vhigh.value(),
            "Chip name": self.chip_name.text(),
            "SMU Resource": self.smu_resource.text().strip() or ct.SMU_RESOURCE,
        }

    def start_or_stop(self):
        if not self.running:
            self.start_task()
        else:
            self.stop_flag["stop"] = True
            self.button.setText("Stopping...")

    def start_task(self):
        params = self.collect_parameters()

        if params["Vlow (V)"] > params["Vhigh (V)"]:
            self.update_label("Error: Vlow must be <= Vhigh")
            self.update_passfail("FAIL")
            return

        if params["Current start (A)"] >= params["Current stop (A)"]:
            self.update_label("Error: Current start must be < max current")
            self.update_passfail("FAIL")
            return

        if params["Selected test pin"] is None:
            self.update_label("Error: Select one pin to test")
            self.update_passfail("FAIL")
            return

        self.running = True
        self.stop_flag["stop"] = False

        self.button.setText("Stop")
        self.passfail_label.setText("RUNNING")
        self.passfail_label.setStyleSheet("background-color: yellow; padding: 6px;")

        self.update_history_row(params["Selected test pin"], "RUNNING", "Test in progress...")
        self.label.setText("Working...")

        threading.Thread(
            target=long_task,
            args=(
                self.update_label,
                self.update_passfail,
                self.update_table_result,
                params,
                self.stop_flag
            ),
            daemon=True
        ).start()

    def update_label(self, text):
        self.label.setText(text)

        if text in ("Done! Reconnect the next pin and run again.", "Stopped", "Stopped due to error"):
            self.running = False
            self.button.setText("Start")

    def update_passfail(self, result):
        if result == "PASS":
            self.passfail_label.setText("PASS")
            self.passfail_label.setStyleSheet("background-color: lightgreen; padding: 6px;")
        elif result == "FAIL":
            self.passfail_label.setText("FAIL")
            self.passfail_label.setStyleSheet("background-color: red; color: white; padding: 6px;")
        elif result == "RUNNING":
            self.passfail_label.setText("RUNNING")
            self.passfail_label.setStyleSheet("background-color: yellow; padding: 6px;")
        else:
            self.passfail_label.setText("READY")
            self.passfail_label.setStyleSheet("background-color: lightgray; padding: 6px;")


if __name__ == "__main__":
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
