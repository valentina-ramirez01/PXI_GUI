import sys
import threading
import time

from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QDoubleSpinBox, QComboBox, QTableWidget,
    QTableWidgetItem, QSpinBox, QGroupBox
)
from PySide6.QtCore import Qt, Signal, QObject


class GuiSignals(QObject):
    label_signal = Signal(str)
    passfail_signal = Signal(str)
    table_signal = Signal(int, str)


def long_task(signals, params, stop_flag):
    pin_count = params["Input pins"]
    vdd = int(params["Vdd pin"])
    gnd = int(params["Gnd pin"])
    tested_pin = int(params["Pin being tested"])

    vlow = params["Vlow (V)"]
    vhigh = params["Vhigh (V)"]

    if tested_pin in (vdd, gnd):
        signals.passfail_signal.emit("FAIL")
        signals.label_signal.emit("Selected pin cannot be Vdd or Gnd.")
        return

    overall_pass = True

    for row_index, pin in enumerate([tested_pin]):

        if stop_flag["stop"]:
            signals.label_signal.emit("Stopped")
            signals.passfail_signal.emit("FAIL")
            return

        time.sleep(0.4)

        voltage = round(0.5 + 0.05 * pin, 3)

        signals.table_signal.emit(row_index, f"{voltage} V")

        if not (vlow <= voltage <= vhigh):
            overall_pass = False

    signals.passfail_signal.emit("PASS" if overall_pass else "FAIL")
    signals.label_signal.emit("Done!")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Continuity Test GUI")
        self.resize(950, 650)

        self.running = False
        self.stop_flag = {"stop": False}

        self.signals = GuiSignals()
        self.signals.label_signal.connect(self.update_label)
        self.signals.passfail_signal.connect(self.update_passfail)
        self.signals.table_signal.connect(self.update_table_result)

        main_layout = QHBoxLayout()

        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)

        dut_label = QLabel("<b>DUT Specifications</b>")
        form.addRow(dut_label)

        self.chip_name = QLineEdit("OPA551")
        form.addRow("Chip name:", self.chip_name)

        self.pins = QSpinBox()
        self.pins.setRange(4, 16)
        self.pins.setValue(8)
        form.addRow("Total pins:", self.pins)

        self.vdd_pin = QComboBox()
        form.addRow("Vdd pin:", self.vdd_pin)

        self.gnd_pin = QComboBox()
        form.addRow("Gnd pin:", self.gnd_pin)

        self.tested_pin = QComboBox()
        form.addRow("Pin being tested:", self.tested_pin)

        test_label = QLabel("<b>Test Conditions</b>")
        form.addRow(test_label)

        self.max_current = QDoubleSpinBox()
        self.max_current.setRange(0.001, 10)
        self.max_current.setValue(1.0)
        self.max_current.setSuffix(" mA")
        form.addRow("Max current:", self.max_current)

        vrange_layout = QHBoxLayout()

        self.vlow = QDoubleSpinBox()
        self.vlow.setRange(0, 1)
        self.vlow.setValue(0.55)
        self.vlow.setSuffix(" V")

        self.vhigh = QDoubleSpinBox()
        self.vhigh.setRange(0, 1)
        self.vhigh.setValue(0.75)
        self.vhigh.setSuffix(" V")

        vrange_layout.addWidget(QLabel("Vlow:"))
        vrange_layout.addWidget(self.vlow)
        vrange_layout.addWidget(QLabel("Vhigh:"))
        vrange_layout.addWidget(self.vhigh)

        form.addRow("Voltage range:", vrange_layout)

        self.passfail_label = QLabel("READY")
        self.passfail_label.setAlignment(Qt.AlignCenter)
        self.passfail_label.setStyleSheet("background-color: lightgray; padding: 6px;")
        form.addRow("Result:", self.passfail_label)

        self.label = QLabel("Ready")

        self.button = QPushButton("Start")
        self.button.clicked.connect(self.start_or_stop)

        self.load_opa_button = QPushButton("Load OPA551 Pinout")
        self.load_opa_button.clicked.connect(self.load_opa551_pinout)

        self.subtitle = QLabel("<b>Continuity Test</b>")
        self.subtitle.setStyleSheet("font-size: 14px;")

        self.description = QLabel(
            "This test measures the selected pin voltage for a forced current. "
            "Vdd and Gnd pins are excluded from testing."
        )
        self.description.setWordWrap(True)
        self.description.setStyleSheet("font-size: 12px; color: #333;")

        left_layout.addWidget(self.subtitle)
        left_layout.addWidget(self.description)
        left_layout.addLayout(form)
        left_layout.addWidget(self.load_opa_button)
        left_layout.addWidget(self.label)
        left_layout.addWidget(self.button)

        pin_group = QGroupBox("Pin Names")
        self.pin_name_form = QFormLayout()
        self.pin_name_boxes = []

        for i in range(16):
            box = QLineEdit()
            box.setPlaceholderText(f"PIN{i + 1}")
            self.pin_name_boxes.append(box)
            self.pin_name_form.addRow(f"Pin {i + 1}:", box)

        pin_group.setLayout(self.pin_name_form)
        right_layout.addWidget(pin_group)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "Pin #", "Pin Name", "Result", "Pass/Fail"
        ])
        right_layout.addWidget(self.table)

        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 1)

        self.setLayout(main_layout)

        self.pins.valueChanged.connect(self.update_pin_choices)
        self.vdd_pin.currentIndexChanged.connect(self.update_pin_choices)
        self.gnd_pin.currentIndexChanged.connect(self.update_pin_choices)
        self.tested_pin.currentIndexChanged.connect(self.update_table_rows)

        self.update_pin_choices()
        self.load_opa551_pinout()

    def get_pin_names(self):
        names = {}
        for i in range(self.pins.value()):
            text = self.pin_name_boxes[i].text().strip()
            names[i + 1] = text if text else f"PIN{i + 1}"
        return names

    def load_opa551_pinout(self):
        names = {
            1: "NC",
            2: "IN+",
            3: "IN-",
            4: "V+",
            5: "NC",
            6: "OUT",
            7: "V-",
            8: "Flag",
        }

        self.pins.setValue(8)

        for i in range(16):
            self.pin_name_boxes[i].clear()

        for pin, name in names.items():
            self.pin_name_boxes[pin - 1].setText(name)

        self.vdd_pin.setCurrentText("5")
        self.gnd_pin.setCurrentText("2")
        self.update_pin_choices()

    def update_pin_choices(self):
        count = int(self.pins.value())

        old_vdd = self.vdd_pin.currentText()
        old_gnd = self.gnd_pin.currentText()
        old_tested = self.tested_pin.currentText()

        for box_index, box in enumerate(self.pin_name_boxes):
            box.setVisible(box_index < count)

        self.vdd_pin.blockSignals(True)
        self.gnd_pin.blockSignals(True)
        self.tested_pin.blockSignals(True)

        self.vdd_pin.clear()
        self.gnd_pin.clear()
        self.tested_pin.clear()

        for i in range(1, count + 1):
            self.vdd_pin.addItem(str(i))
            self.gnd_pin.addItem(str(i))
            self.tested_pin.addItem(str(i))

        if old_vdd in [str(i) for i in range(1, count + 1)]:
            self.vdd_pin.setCurrentText(old_vdd)

        if old_gnd in [str(i) for i in range(1, count + 1)]:
            self.gnd_pin.setCurrentText(old_gnd)

        if old_tested in [str(i) for i in range(1, count + 1)]:
            self.tested_pin.setCurrentText(old_tested)

        if self.vdd_pin.currentText() == self.gnd_pin.currentText():
            idx = (self.vdd_pin.currentIndex() + 1) % count
            self.gnd_pin.setCurrentIndex(idx)

        if self.tested_pin.currentText() in (
            self.vdd_pin.currentText(),
            self.gnd_pin.currentText()
        ):
            for i in range(count):
                candidate = str(i + 1)
                if candidate not in (
                    self.vdd_pin.currentText(),
                    self.gnd_pin.currentText()
                ):
                    self.tested_pin.setCurrentText(candidate)
                    break

        self.vdd_pin.blockSignals(False)
        self.gnd_pin.blockSignals(False)
        self.tested_pin.blockSignals(False)

        self.update_table_rows()

    def update_table_rows(self):
        if not self.tested_pin.currentText():
            return

        pin = int(self.tested_pin.currentText())
        names = self.get_pin_names()
        pin_name = names.get(pin, f"PIN{pin}")

        self.table.setRowCount(1)

        values = [str(pin), pin_name, "—", "READY"]

        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(0, col, item)

    def update_table_result(self, row, result):
        pin = int(self.tested_pin.currentText())
        names = self.get_pin_names()
        pin_name = names.get(pin, f"PIN{pin}")

        voltage = float(result.replace(" V", ""))

        passed = self.vlow.value() <= voltage <= self.vhigh.value()

        values = [
            str(pin),
            pin_name,
            result,
            "PASS" if passed else "FAIL"
        ]

        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)

            if col == 3:
                item.setBackground(Qt.green if passed else Qt.red)

            self.table.setItem(row, col, item)

    def collect_parameters(self):
        return {
            "Input pins": int(self.pins.value()),
            "V+ pin": self.vdd_pin.currentText(),
            "V- pin": self.gnd_pin.currentText(),
            "Pin being tested": self.tested_pin.currentText(),
            "Max current (mA)": self.max_current.value(),
            "Vlow (V)": self.vlow.value(),
            "Vhigh (V)": self.vhigh.value(),
            "Chip name": self.chip_name.text(),
            "Pin Names": self.get_pin_names(),
        }

    def start_or_stop(self):
        if not self.running:
            self.start_task()
        else:
            self.stop_flag["stop"] = True
            self.button.setText("Stopping...")

    def start_task(self):
        self.running = True
        self.stop_flag["stop"] = False

        self.button.setText("Stop")
        self.passfail_label.setText("RUNNING")
        self.passfail_label.setStyleSheet("background-color: yellow; padding: 6px;")
        self.label.setText("Working...")

        self.update_table_rows()

        params = self.collect_parameters()

        threading.Thread(
            target=long_task,
            args=(self.signals, params, self.stop_flag),
            daemon=True
        ).start()

    def update_label(self, text):
        self.label.setText(text)

        if text in ("Done!", "Stopped") or "Selected pin" in text:
            self.running = False
            self.button.setText("Start")

    def update_passfail(self, result):
        if result == "PASS":
            self.passfail_label.setText("PASS")
            self.passfail_label.setStyleSheet(
                "background-color: lightgreen; padding: 6px;"
            )
        elif result == "FAIL":
            self.passfail_label.setText("FAIL")
            self.passfail_label.setStyleSheet(
                "background-color: red; color: white; padding: 6px;"
            )
        else:
            self.passfail_label.setText("READY")
            self.passfail_label.setStyleSheet(
                "background-color: lightgray; padding: 6px;"
            )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())