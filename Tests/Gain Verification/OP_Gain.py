from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QDoubleSpinBox, QTableWidget, QTableWidgetItem
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
import threading

from OPGain_test import run_open_loop_gain_test


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("OPA551 Open-Loop Gain GUI")
        self.resize(1400, 700)
        self.running = False

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)

        form.addRow(QLabel("<h2>OPA551 Open-Loop Gain Test</h2>"))

        self.smu_resource = QLineEdit("SMU")
        form.addRow("PXIe-4138 Resource:", self.smu_resource)

        self.ps_resource = QLineEdit("PXI4110")
        form.addRow("PXI-4110 Resource:", self.ps_resource)

        self.dmm_resource = QLineEdit("PXI4080")
        form.addRow("PXIe-4080 Resource:", self.dmm_resource)

        self.pos_channel = QLineEdit("1")
        form.addRow("+15V Channel:", self.pos_channel)

        self.neg_channel = QLineEdit("2")
        form.addRow("-15V Channel:", self.neg_channel)

        form.addRow(QLabel("<b>Supply Conditions</b>"))

        self.pos_supply = QDoubleSpinBox()
        self.pos_supply.setRange(0, 30)
        self.pos_supply.setDecimals(3)
        self.pos_supply.setValue(15.0)
        self.pos_supply.setSuffix(" V")
        form.addRow("+ Supply:", self.pos_supply)

        self.neg_supply = QDoubleSpinBox()
        self.neg_supply.setRange(-30, 0)
        self.neg_supply.setDecimals(3)
        self.neg_supply.setValue(-15.0)
        self.neg_supply.setSuffix(" V")
        form.addRow("- Supply:", self.neg_supply)

        form.addRow(QLabel("<b>VSRC1 Test Points</b>"))

        self.vsrc1_1 = QDoubleSpinBox()
        self.vsrc1_1.setRange(-10, 10)
        self.vsrc1_1.setDecimals(6)
        self.vsrc1_1.setValue(0.0)
        self.vsrc1_1.setSuffix(" V")
        form.addRow("VSRC1 Point 1:", self.vsrc1_1)

        self.vsrc1_2 = QDoubleSpinBox()
        self.vsrc1_2.setRange(-10, 10)
        self.vsrc1_2.setDecimals(6)
        self.vsrc1_2.setValue(0.001)
        self.vsrc1_2.setSuffix(" V")
        form.addRow("VSRC1 Point 2:", self.vsrc1_2)

        form.addRow(QLabel("<b>Resistor Values</b>"))

        self.r1 = QDoubleSpinBox()
        self.r1.setRange(1, 1e6)
        self.r1.setDecimals(1)
        self.r1.setValue(1000.0)
        self.r1.setSuffix(" Ω")
        form.addRow("R1:", self.r1)

        self.r2 = QDoubleSpinBox()
        self.r2.setRange(1, 10e6)
        self.r2.setDecimals(1)
        self.r2.setValue(100000.0)
        self.r2.setSuffix(" Ω")
        form.addRow("R2:", self.r2)

        self.pass_limit = QDoubleSpinBox()
        self.pass_limit.setRange(0, 200)
        self.pass_limit.setDecimals(2)
        self.pass_limit.setValue(70.0)
        self.pass_limit.setSuffix(" dB")
        form.addRow("Pass if gain ≥", self.pass_limit)

        self.result_box = QLabel("READY")
        self.result_box.setAlignment(Qt.AlignCenter)
        self.set_result_box("READY")
        form.addRow("Result:", self.result_box)

        self.status_label = QLabel("Ready")
        form.addRow(self.status_label)

        self.start_button = QPushButton("Start Test")
        self.start_button.clicked.connect(self.start_test)
        form.addRow(self.start_button)

        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels([
            "Status",
            "Gain dB",
            "Gain V/V",
            "VSRC1 1",
            "VSRC1 2",
            "VNULL 1",
            "VNULL 2",
            "ΔVSRC1",
            "ΔVNULL",
            "+Supply",
            "-Supply",
            "Notes"
        ])

        left_layout = QVBoxLayout()
        left_layout.addLayout(form)

        main_layout = QHBoxLayout()
        main_layout.addLayout(left_layout, 1)
        main_layout.addWidget(self.table, 2)

        self.setLayout(main_layout)

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

    def start_test(self):
        if self.running:
            return

        self.running = True
        self.start_button.setEnabled(False)
        self.set_result_box("RUNNING")
        self.status_label.setText("Running open-loop gain test...")

        threading.Thread(target=self.run_test_thread, daemon=True).start()

    def run_test_thread(self):
        try:
            results = run_open_loop_gain_test(
                vsrc1_1=self.vsrc1_1.value(),
                vsrc1_2=self.vsrc1_2.value(),
                pos_supply=self.pos_supply.value(),
                neg_supply=self.neg_supply.value()
            )

            self.populate_results(results)

        except Exception as e:
            self.add_error_row(str(e))
            self.set_result_box("FAIL")
            self.status_label.setText("Test error.")

        self.running = False
        self.start_button.setEnabled(True)

    def populate_results(self, results):
        if results.get("error"):
            self.add_error_row(results["error"])
            self.set_result_box("FAIL")
            self.status_label.setText("Test failed with error.")
            return

        calc = results["calculation"]
        p1 = results["point_1"]
        p2 = results["point_2"]
        power = results["power_up"]

        gain_db = calc.get("gain_dB")
        gain_vv = calc.get("gain_V_per_V")

        if gain_db is not None and gain_db >= self.pass_limit.value():
            status = "PASS"
        else:
            status = "FAIL"

        row = self.table.rowCount()
        self.table.insertRow(row)

        status_item = QTableWidgetItem(status)
        if status == "PASS":
            status_item.setBackground(QColor(0, 220, 0))
            status_item.setForeground(QColor(255, 255, 255))
        else:
            status_item.setBackground(QColor(220, 0, 0))
            status_item.setForeground(QColor(255, 255, 255))

        self.table.setItem(row, 0, status_item)
        self.table.setItem(row, 1, QTableWidgetItem(f"{gain_db:.2f} dB" if gain_db is not None else "—"))
        self.table.setItem(row, 2, QTableWidgetItem(f"{gain_vv:.3f}" if gain_vv is not None else "—"))
        self.table.setItem(row, 3, QTableWidgetItem(f"{p1['vsrc1_measured_V']:.9f} V"))
        self.table.setItem(row, 4, QTableWidgetItem(f"{p2['vsrc1_measured_V']:.9f} V"))
        self.table.setItem(row, 5, QTableWidgetItem(f"{p1['vnull_avg_V']:.9f} V"))
        self.table.setItem(row, 6, QTableWidgetItem(f"{p2['vnull_avg_V']:.9f} V"))
        self.table.setItem(row, 7, QTableWidgetItem(f"{calc['delta_vsrc1_V']:.9f} V"))
        self.table.setItem(row, 8, QTableWidgetItem(f"{calc['delta_vnull_V']:.9f} V"))

        self.table.setItem(row, 9, QTableWidgetItem(
            f"{power['positive_supply']['voltage_V']:.6f} V, "
            f"{power['positive_supply']['current_A']:.6f} A"
        ))

        self.table.setItem(row, 10, QTableWidgetItem(
            f"{power['negative_supply']['voltage_V']:.6f} V, "
            f"{power['negative_supply']['current_A']:.6f} A"
        ))

        note = calc.get("error") or "Open-loop gain calculated from professor nulling equation."
        self.table.setItem(row, 11, QTableWidgetItem(note))

        self.set_result_box(status)
        self.status_label.setText(f"Done. Gain = {gain_db:.2f} dB. Results kept in table.")

    def add_error_row(self, error_text):
        row = self.table.rowCount()
        self.table.insertRow(row)

        status_item = QTableWidgetItem("FAIL")
        status_item.setBackground(QColor(220, 0, 0))
        status_item.setForeground(QColor(255, 255, 255))

        self.table.setItem(row, 0, status_item)
        self.table.setItem(row, 11, QTableWidgetItem(error_text))


if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()