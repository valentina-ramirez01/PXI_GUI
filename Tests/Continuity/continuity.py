from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QDoubleSpinBox, QComboBox, QTableWidget,
    QTableWidgetItem, QSpinBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
import threading

from continuity_test import run_full_diode_sweep_test


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Continuity Test GUI - Single Pin")
        self.resize(1400, 700)
        self.running = False

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)

        form.addRow(QLabel("<h2>Continuity Test - One Pin at a Time</h2>"))

        self.chip_name = QLineEdit()
        form.addRow("Chip name:", self.chip_name)

        self.total_pins = QSpinBox()
        self.total_pins.setRange(4, 64)
        self.total_pins.setValue(8)
        self.total_pins.valueChanged.connect(self.update_pin_dropdowns)
        form.addRow("Total pins:", self.total_pins)

        self.vplus_pin = QComboBox()
        form.addRow("V+ pin not tested:", self.vplus_pin)

        self.gnd_pin = QComboBox()
        form.addRow("V- / GND pin not tested:", self.gnd_pin)

        self.test_pin = QComboBox()
        form.addRow("Pin number to test now:", self.test_pin)

        self.pin_name = QLineEdit()
        form.addRow("Pin name to test now:", self.pin_name)

        self.current_selection = QLabel("No pin selected")
        form.addRow("Current selection:", self.current_selection)

        self.smu_resource = QLineEdit("SMU")
        form.addRow("SMU resource:", self.smu_resource)

        form.addRow(QLabel("<b>Test Conditions</b>"))

        self.max_current = QDoubleSpinBox()
        self.max_current.setDecimals(3)
        self.max_current.setRange(0.001, 10.0)
        self.max_current.setValue(0.800)
        self.max_current.setSuffix(" mA")
        form.addRow("Max current:", self.max_current)

        fw_layout = QHBoxLayout()
        self.forward_low = QDoubleSpinBox()
        self.forward_low.setRange(0, 2)
        self.forward_low.setValue(0.6)
        self.forward_low.setSuffix(" V")

        self.forward_high = QDoubleSpinBox()
        self.forward_high.setRange(0, 2)
        self.forward_high.setValue(0.8)
        self.forward_high.setSuffix(" V")

        fw_layout.addWidget(QLabel("Vlow:"))
        fw_layout.addWidget(self.forward_low)
        fw_layout.addWidget(QLabel("Vhigh:"))
        fw_layout.addWidget(self.forward_high)
        form.addRow("Forward voltage range:", fw_layout)

        rev_layout = QHBoxLayout()
        self.reverse_low = QDoubleSpinBox()
        self.reverse_low.setRange(-2, 0)
        self.reverse_low.setValue(-0.8)
        self.reverse_low.setSuffix(" V")

        self.reverse_high = QDoubleSpinBox()
        self.reverse_high.setRange(-2, 0)
        self.reverse_high.setValue(-0.6)
        self.reverse_high.setSuffix(" V")

        rev_layout.addWidget(QLabel("Vlow:"))
        rev_layout.addWidget(self.reverse_low)
        rev_layout.addWidget(QLabel("Vhigh:"))
        rev_layout.addWidget(self.reverse_high)
        form.addRow("Reverse voltage range:", rev_layout)

        self.result_box = QLabel("READY")
        self.result_box.setAlignment(Qt.AlignCenter)
        self.set_result_box("READY")
        form.addRow("Result:", self.result_box)

        self.status_label = QLabel("Ready")
        form.addRow(self.status_label)

        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Test")
        self.start_button.clicked.connect(self.start_test)

        self.next_button = QPushButton("Next Pin")
        self.next_button.clicked.connect(self.next_pin)

        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.next_button)
        form.addRow(button_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Pin Name",
            "Sweep",
            "Status",
            "Avg Voltage",
            "Min Voltage",
            "Max Voltage",
            "Current to Target"
        ])

        left_layout = QVBoxLayout()
        left_layout.addLayout(form)

        main_layout = QHBoxLayout()
        main_layout.addLayout(left_layout, 1)
        main_layout.addWidget(self.table, 2)
        self.setLayout(main_layout)

        self.update_pin_dropdowns()
        self.test_pin.currentIndexChanged.connect(self.update_current_selection)
        self.pin_name.textChanged.connect(self.update_current_selection)

    def set_result_box(self, result):
        if result == "PASS":
            color = "limegreen"
            text_color = "white"
        elif result == "FAIL":
            color = "red"
            text_color = "white"
        elif result == "RUNNING":
            color = "yellow"
            text_color = "black"
        else:
            color = "lightgray"
            text_color = "black"

        self.result_box.setText(result)
        self.result_box.setStyleSheet(f"""
            background-color: {color};
            color: {text_color};
            font-size: 18px;
            font-weight: bold;
            padding: 10px;
        """)

    def update_pin_dropdowns(self):
        total = self.total_pins.value()

        self.vplus_pin.clear()
        self.gnd_pin.clear()
        self.test_pin.clear()

        for i in range(1, total + 1):
            self.vplus_pin.addItem(str(i))
            self.gnd_pin.addItem(str(i))

        self.vplus_pin.setCurrentText("7")
        self.gnd_pin.setCurrentText("4")

        excluded = [int(self.vplus_pin.currentText()), int(self.gnd_pin.currentText())]

        for i in range(1, total + 1):
            if i not in excluded:
                self.test_pin.addItem(str(i))

        self.update_current_selection()

    def update_current_selection(self):
        pin_name = self.pin_name.text().strip() or "(No label)"
        self.current_selection.setText(f"Selected pin: {pin_name}")

    def start_test(self):
        if self.running:
            return

        pin_name = self.pin_name.text().strip()
        if pin_name == "":
            self.status_label.setText("Enter a pin name first.")
            return

        self.running = True
        self.start_button.setEnabled(False)
        self.set_result_box("RUNNING")
        self.status_label.setText(f"Testing {pin_name}...")

        threading.Thread(target=self.run_test_thread, daemon=True).start()

    def run_test_thread(self):
        pin_name = self.pin_name.text().strip()

        try:
            results = run_full_diode_sweep_test(
                input_pin=pin_name,
                smu_resource=self.smu_resource.text(),
                current_stop=self.max_current.value() * 1e-3,
                forward_min=self.forward_low.value(),
                forward_max=self.forward_high.value(),
                reverse_min=self.reverse_low.value(),
                reverse_max=self.reverse_high.value()
            )

            self.populate_results(results, pin_name)

        except Exception as e:
            self.set_result_box("FAIL")
            self.status_label.setText(str(e))

        self.running = False
        self.start_button.setEnabled(True)

    def populate_results(self, results, pin_name):
        if results.get("error"):
            self.add_error_row(pin_name, results["error"])
            self.set_result_box("FAIL")
            self.status_label.setText(f"Error testing {pin_name}.")
            return

        sweeps = [results["forward_sweep"], results["reverse_sweep"]]
        overall_pass = True

        for sweep in sweeps:
            row = self.table.rowCount()
            self.table.insertRow(row)

            status = sweep["status"]
            if status != "PASS":
                overall_pass = False

            self.table.setItem(row, 0, QTableWidgetItem(pin_name))
            self.table.setItem(row, 1, QTableWidgetItem(sweep["test"].replace(" DIODE SWEEP", "")))

            status_item = QTableWidgetItem(status)
            if status == "PASS":
                status_item.setBackground(QColor(0, 220, 0))
                status_item.setForeground(QColor(255, 255, 255))
            else:
                status_item.setBackground(QColor(220, 0, 0))
                status_item.setForeground(QColor(255, 255, 255))
            self.table.setItem(row, 2, status_item)

            if status == "PASS":
                self.table.setItem(row, 3, QTableWidgetItem(f"{sweep['avg_voltage_V']:.6f} V"))
                self.table.setItem(row, 4, QTableWidgetItem(f"{sweep['min_voltage_V']:.6f} V"))
                self.table.setItem(row, 5, QTableWidgetItem(f"{sweep['max_voltage_V']:.6f} V"))
                self.table.setItem(row, 6, QTableWidgetItem(f"{sweep['current_to_target_mA']:.6f} mA"))
            else:
                self.table.setItem(row, 3, QTableWidgetItem("—"))
                self.table.setItem(row, 4, QTableWidgetItem("—"))
                self.table.setItem(row, 5, QTableWidgetItem("—"))
                self.table.setItem(row, 6, QTableWidgetItem(f"{sweep.get('current_to_target_mA', 0):.6f} mA"))

        if overall_pass:
            self.set_result_box("PASS")
            self.status_label.setText(f"Done testing {pin_name}: PASS. Results kept in table.")
        else:
            self.set_result_box("FAIL")
            self.status_label.setText(f"Done testing {pin_name}: FAIL. Results kept in table.")

    def add_error_row(self, pin_name, error_text):
        row = self.table.rowCount()
        self.table.insertRow(row)

        self.table.setItem(row, 0, QTableWidgetItem(pin_name))
        self.table.setItem(row, 1, QTableWidgetItem("ERROR"))

        status_item = QTableWidgetItem("FAIL")
        status_item.setBackground(QColor(220, 0, 0))
        status_item.setForeground(QColor(255, 255, 255))
        self.table.setItem(row, 2, status_item)

        self.table.setItem(row, 3, QTableWidgetItem(error_text))
        self.table.setItem(row, 4, QTableWidgetItem("—"))
        self.table.setItem(row, 5, QTableWidgetItem("—"))
        self.table.setItem(row, 6, QTableWidgetItem("—"))

    def next_pin(self):
        current = self.test_pin.currentIndex()

        if current < self.test_pin.count() - 1:
            self.test_pin.setCurrentIndex(current + 1)

        self.pin_name.clear()
        self.set_result_box("READY")
        self.status_label.setText("Ready for next pin. Previous results kept in table.")


if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()