from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel,
    QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QDoubleSpinBox, QComboBox, QTableWidget, QTableWidgetItem,
    QSpinBox, QCheckBox, QGroupBox, QTabWidget
)
from PySide6.QtCore import Qt
from qtutils import inmain_later
import threading
import time


# ==========================================================
# Worker thread
# ==========================================================
def long_task(callback, passfail_callback, table_callback, params, stop_flag):

    pin_count = params["Input pins"]
    vdd = int(params["Vdd pin"])
    gnd = int(params["Gnd pin"])
    nc_pins = params["NC pins"]

    vlow = params["Vlow (V)"]
    vhigh = params["Vhigh (V)"]

    test_pins = [
        p for p in range(1, pin_count + 1)
        if p not in (vdd, gnd) and p not in nc_pins
    ]

    overall_pass = True

    for row_index, pin in enumerate(test_pins):

        if stop_flag["stop"]:
            inmain_later(callback, "Stopped")
            inmain_later(passfail_callback, "FAIL")
            return

        time.sleep(0.4)

        voltage = round(0.5 + 0.05 * pin, 3)

        inmain_later(table_callback, row_index, f"{voltage} V")

        if not (vlow <= voltage <= vhigh):
            overall_pass = False

    inmain_later(passfail_callback, "PASS" if overall_pass else "FAIL")
    inmain_later(callback, "Done!")


# ==========================================================
# DUT TAB (separate widget)
# ==========================================================
class DUTTab(QWidget):
    def __init__(self):
        super().__init__()

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)

        title = QLabel("<b>DUT Specifications</b>")
        form.addRow(title)

        self.chip_name = QLineEdit()
        form.addRow("Chip name:", self.chip_name)

        self.pins = QSpinBox()
        self.pins.setRange(4, 12)
        form.addRow("Pins:", self.pins)

        self.vdd_pin = QComboBox()
        form.addRow("Vdd pin:", self.vdd_pin)

        self.gnd_pin = QComboBox()
        form.addRow("Gnd pin:", self.gnd_pin)

        # ---------- NC CHECKBOXES ----------
        self.nc_group = QGroupBox("No-Connection Pins")
        nc_layout = QHBoxLayout()

        col1 = QVBoxLayout()
        col2 = QVBoxLayout()

        self.nc_checkboxes = []

        for i in range(1, 13):
            cb = QCheckBox(f"Pin {i}")
            self.nc_checkboxes.append(cb)

            if i % 2:
                col1.addWidget(cb)
            else:
                col2.addWidget(cb)

        nc_layout.addLayout(col1)
        nc_layout.addLayout(col2)
        self.nc_group.setLayout(nc_layout)

        form.addRow(self.nc_group)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addStretch()

        self.setLayout(layout)


# ==========================================================
# TEST TAB
# ==========================================================
class TestTab(QWidget):
    def __init__(self):
        super().__init__()

        # ---------- TABLE ----------
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Pin", "Result"])

        # ---------- TEST CONDITIONS ----------
        form = QFormLayout()

        label = QLabel("<b>Test Conditions</b>")
        form.addRow(label)

        self.max_current = QDoubleSpinBox()
        self.max_current.setRange(1, 10)
        self.max_current.setSuffix(" mA")
        form.addRow("Max current:", self.max_current)

        vrange_layout = QHBoxLayout()

        self.vlow = QDoubleSpinBox()
        self.vlow.setRange(0, 1)
        self.vlow.setSuffix(" V")

        self.vhigh = QDoubleSpinBox()
        self.vhigh.setRange(0, 1)
        self.vhigh.setSuffix(" V")

        self.vlow.setValue(0.55)
        self.vhigh.setValue(0.75)

        vrange_layout.addWidget(QLabel("Vlow:"))
        vrange_layout.addWidget(self.vlow)
        vrange_layout.addWidget(QLabel("Vhigh:"))
        vrange_layout.addWidget(self.vhigh)

        form.addRow("Voltage range:", vrange_layout)

        self.passfail_label = QLabel("READY")
        self.passfail_label.setStyleSheet(
            "background-color: lightgray; padding:6px;"
        )
        form.addRow("Result:", self.passfail_label)

        # ---------- DESCRIPTION ----------
        self.subtitle = QLabel("<b>Continuity Test</b>")
        self.description = QLabel(
            "Measures per-pin voltages for forced current. "
            "Vdd, Gnd, and N.C. pins are excluded."
        )
        self.description.setWordWrap(True)

        self.status = QLabel("Ready")

        self.button = QPushButton("Start")

        # ---------- LAYOUT ----------
        left = QVBoxLayout()
        left.addWidget(self.subtitle)
        left.addWidget(self.description)
        left.addLayout(form)
        left.addWidget(self.status)
        left.addWidget(self.button)

        layout = QHBoxLayout()
        layout.addLayout(left, 1)
        layout.addWidget(self.table, 1)

        self.setLayout(layout)


# ==========================================================
# MAIN WINDOW
# ==========================================================
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("DUT GUI")
        self.resize(700, 300)

        self.running = False
        self.stop_flag = {"stop": False}

        # ---------- Tabs ----------
        self.tabs = QTabWidget()

        self.dut_tab = DUTTab()
        self.test_tab = TestTab()

        self.tabs.addTab(self.dut_tab, "DUT Setup")
        self.tabs.addTab(self.test_tab, "Continuity Test")

        layout = QVBoxLayout()
        layout.addWidget(self.tabs)
        self.setLayout(layout)

        # ---------- SIGNALS ----------
        self.dut_tab.pins.valueChanged.connect(self.update_pin_choices)
        self.dut_tab.vdd_pin.currentIndexChanged.connect(self.update_pin_choices)
        self.dut_tab.gnd_pin.currentIndexChanged.connect(self.update_pin_choices)

        for cb in self.dut_tab.nc_checkboxes:
            cb.stateChanged.connect(self.update_table_rows)

        self.test_tab.button.clicked.connect(self.start_or_stop)

        self.update_pin_choices()

    # ======================================================
    # Pin Updates
    # ======================================================
    def update_pin_choices(self):

        count = int(self.dut_tab.pins.value())

        vdd_box = self.dut_tab.vdd_pin
        gnd_box = self.dut_tab.gnd_pin

        # ---- BLOCK SIGNALS (IMPORTANT) ----
        vdd_box.blockSignals(True)
        gnd_box.blockSignals(True)

        old_vdd = vdd_box.currentText()
        old_gnd = gnd_box.currentText()

        vdd_box.clear()
        gnd_box.clear()

        for i in range(1, count + 1):
            vdd_box.addItem(str(i))
            gnd_box.addItem(str(i))

        # Restore previous selections if valid
        if old_vdd in [str(i) for i in range(1, count + 1)]:
            vdd_box.setCurrentText(old_vdd)

        if old_gnd in [str(i) for i in range(1, count + 1)]:
            gnd_box.setCurrentText(old_gnd)

        # Prevent same pin selection
        if vdd_box.currentText() == gnd_box.currentText():
            idx = (vdd_box.currentIndex() + 1) % count
            gnd_box.setCurrentIndex(idx)

        # ---- UNBLOCK SIGNALS ----
        vdd_box.blockSignals(False)
        gnd_box.blockSignals(False)

        # Safe updates
        self.update_nc_checkboxes()
        self.update_table_rows()

    def update_nc_checkboxes(self):
        count = self.dut_tab.pins.value()
        vdd = int(self.dut_tab.vdd_pin.currentText())
        gnd = int(self.dut_tab.gnd_pin.currentText())

        for i, cb in enumerate(self.dut_tab.nc_checkboxes, start=1):

            cb.setVisible(i <= count)

            if i in (vdd, gnd):
                cb.setChecked(False)
                cb.setEnabled(False)
            else:
                cb.setEnabled(True)

    def update_table_rows(self):
        count = self.dut_tab.pins.value()
        vdd = int(self.dut_tab.vdd_pin.currentText())
        gnd = int(self.dut_tab.gnd_pin.currentText())

        nc = [
            i for i, cb in enumerate(self.dut_tab.nc_checkboxes, start=1)
            if cb.isChecked()
        ]

        test_pins = [
            p for p in range(1, count + 1)
            if p not in (vdd, gnd) and p not in nc
        ]

        table = self.test_tab.table
        table.setRowCount(len(test_pins))

        for row, pin in enumerate(test_pins):
            table.setItem(row, 0, QTableWidgetItem(str(pin)))
            table.setItem(row, 1, QTableWidgetItem("—"))

    # ======================================================
    # Parameters
    # ======================================================
    def collect_parameters(self):
        return {
            "Input pins": self.dut_tab.pins.value(),
            "Vdd pin": self.dut_tab.vdd_pin.currentText(),
            "Gnd pin": self.dut_tab.gnd_pin.currentText(),
            "NC pins": [
                i for i, cb in enumerate(self.dut_tab.nc_checkboxes, start=1)
                if cb.isChecked()
            ],
            "Max current (mA)": self.test_tab.max_current.value(),
            "Vlow (V)": self.test_tab.vlow.value(),
            "Vhigh (V)": self.test_tab.vhigh.value(),
            "Chip name": self.dut_tab.chip_name.text(),
        }

    # ======================================================
    # Start / Stop
    # ======================================================
    def start_or_stop(self):
        if not self.running:
            self.start_task()
        else:
            self.stop_flag["stop"] = True
            self.test_tab.button.setText("Stopping...")

    def start_task(self):

        self.running = True
        self.stop_flag["stop"] = False

        self.tabs.setCurrentWidget(self.test_tab)

        self.test_tab.button.setText("Stop")
        self.test_tab.passfail_label.setText("RUNNING")
        self.test_tab.passfail_label.setStyleSheet(
            "background-color: yellow; padding:6px;"
        )

        params = self.collect_parameters()

        threading.Thread(
            target=long_task,
            args=(
                self.update_status,
                self.update_passfail,
                self.update_table_result,
                params,
                self.stop_flag,
            ),
            daemon=True,
        ).start()

    # ======================================================
    # GUI Updates
    # ======================================================
    def update_status(self, text):
        self.test_tab.status.setText(text)

        if text in ("Done!", "Stopped"):
            self.running = False
            self.test_tab.button.setText("Start")

    def update_passfail(self, result):

        label = self.test_tab.passfail_label

        if result == "PASS":
            label.setText("PASS")
            label.setStyleSheet("background:lightgreen;padding:6px;")

        elif result == "FAIL":
            label.setText("FAIL")
            label.setStyleSheet("background:red;color:white;padding:6px;")

    def update_table_result(self, row, result):
        self.test_tab.table.setItem(row, 1, QTableWidgetItem(result))


# ==========================================================
# RUN
# ==========================================================
if __name__ == "__main__":
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()