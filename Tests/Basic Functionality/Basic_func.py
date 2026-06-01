import sys
import time
import numpy as np

import nidcpower
import nidmm

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit,
    QDoubleSpinBox, QSpinBox, QVBoxLayout, QHBoxLayout,
    QFormLayout, QTableWidget, QTableWidgetItem, QMessageBox,
    QGroupBox
)

DMM_DIGITS_DEFAULT = 5.5


def parse_sweep(text):
    values = []
    for item in text.split(","):
        item = item.strip()
        if item:
            values.append(float(item))
    return values


class FunctionalityWorker(QThread):
    result_signal = Signal(dict)
    status_signal = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, settings):
        super().__init__()
        self.s = settings

    def run(self):
        psu = None
        smu = None
        dmm = None

        try:
            chip = self.s["chip_name"]
            expected_gain = 1.0 + (self.s["rf"] / self.s["rg"])
            vin_values = parse_sweep(self.s["vin_sweep"])

            self.status_signal.emit("Opening instrument sessions...")

            psu = nidcpower.Session(self.s["psu_resource"])
            smu = nidcpower.Session(self.s["smu_resource"])
            dmm = nidmm.Session(self.s["dmm_resource"])

            self.status_signal.emit("Configuring PXI-4110 supplies...")

            pos_ch = psu.channels[self.s["psu_pos_ch"]]
            neg_ch = psu.channels[self.s["psu_neg_ch"]]

            pos_ch.output_function = nidcpower.OutputFunction.DC_VOLTAGE
            pos_ch.voltage_level = self.s["vplus"]
            pos_ch.current_limit = self.s["psu_current_limit"]
            pos_ch.output_enabled = True

            neg_ch.output_function = nidcpower.OutputFunction.DC_VOLTAGE
            neg_ch.voltage_level = self.s["vminus"]
            neg_ch.current_limit = self.s["psu_current_limit"]
            neg_ch.output_enabled = True

            psu.initiate()

            self.status_signal.emit("Configuring PXIe-4138 input source...")

            smu.output_function = nidcpower.OutputFunction.DC_VOLTAGE
            smu.voltage_level = 0.0
            smu.current_limit = self.s["smu_current_limit"]
            smu.output_enabled = True
            smu.initiate()

            self.status_signal.emit("Configuring PXIe-4080 DMM...")

            dmm.configure_measurement_digits(
                nidmm.Function.DC_VOLTS,
                self.s["dmm_range"],
                DMM_DIGITS_DEFAULT
            )

            time.sleep(self.s["initial_delay"])

            all_pass = True

            for vin in vin_values:
                self.status_signal.emit(f"Testing Vin = {vin:.4f} V...")

                smu.voltage_level = vin
                time.sleep(self.s["settling_time"])

                samples = []

                for _ in range(self.s["sample_count"]):
                    vout = dmm.read(self.s["dmm_timeout"])
                    samples.append(vout)

                vout_avg = float(np.mean(samples))
                vout_std = float(np.std(samples))
                expected_vout = expected_gain * vin

                if abs(vin) < 1e-12:
                    measured_gain = np.nan
                    gain_error_percent = np.nan
                    passed = abs(vout_avg) <= self.s["zero_tolerance"]
                else:
                    measured_gain = vout_avg / vin
                    gain_error_percent = abs(
                        (measured_gain - expected_gain) / expected_gain
                    ) * 100.0
                    passed = gain_error_percent <= self.s["gain_tolerance_percent"]

                if not passed:
                    all_pass = False

                self.result_signal.emit({
                    "vin": vin,
                    "vout": vout_avg,
                    "vout_std": vout_std,
                    "expected_vout": expected_vout,
                    "expected_gain": expected_gain,
                    "measured_gain": measured_gain,
                    "gain_error_percent": gain_error_percent,
                    "passed": passed,
                })

            smu.voltage_level = 0.0

            final_msg = (
                f"PASS: {chip} is amplifying correctly. "
                f"Expected gain = {expected_gain:.3f} V/V."
                if all_pass else
                f"FAIL: {chip} did not meet the gain tolerance. "
                f"Expected gain = {expected_gain:.3f} V/V."
            )

            self.finished_signal.emit(all_pass, final_msg)

        except Exception as e:
            self.finished_signal.emit(False, f"TEST ERROR: {e}")

        finally:
            try:
                if smu:
                    smu.voltage_level = 0.0
                    smu.output_enabled = False
                    smu.close()
            except:
                pass

            try:
                if psu:
                    psu.channels[self.s["psu_pos_ch"]].output_enabled = False
                    psu.channels[self.s["psu_neg_ch"]].output_enabled = False
                    psu.close()
            except:
                pass

            try:
                if dmm:
                    dmm.close()
            except:
                pass


class FunctionalityGUI(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Basic Functionality Test")
        self.resize(1150, 700)

        self.worker = None

        main_layout = QVBoxLayout()

        instrument_group = QGroupBox("Instrument Resource Names")
        instrument_form = QFormLayout()

        self.psu_resource = QLineEdit("PXI4110")
        self.smu_resource = QLineEdit("SMU")
        self.dmm_resource = QLineEdit("PXI4080")
        self.psu_pos_ch = QLineEdit("1")
        self.psu_neg_ch = QLineEdit("2")

        instrument_form.addRow("PXI-4110 Resource:", self.psu_resource)
        instrument_form.addRow("PXIe-4138 Vin Resource:", self.smu_resource)
        instrument_form.addRow("PXIe-4080 DMM Resource:", self.dmm_resource)
        instrument_form.addRow("+15 V PSU Channel:", self.psu_pos_ch)
        instrument_form.addRow("-15 V PSU Channel:", self.psu_neg_ch)

        instrument_group.setLayout(instrument_form)

        dut_group = QGroupBox("DUT / Circuit Settings")
        dut_form = QFormLayout()

        self.chip_name = QLineEdit("OPA551")

        self.vplus = QDoubleSpinBox()
        self.vplus.setRange(0, 20)
        self.vplus.setValue(15.0)
        self.vplus.setSuffix(" V")

        self.vminus = QDoubleSpinBox()
        self.vminus.setRange(-20, 0)
        self.vminus.setValue(-15.0)
        self.vminus.setSuffix(" V")

        self.rf = QDoubleSpinBox()
        self.rf.setRange(1, 1_000_000)
        self.rf.setValue(10000)
        self.rf.setSuffix(" Ω")

        self.rg = QDoubleSpinBox()
        self.rg.setRange(1, 1_000_000)
        self.rg.setDecimals(2)
        self.rg.setValue(1111.11)
        self.rg.setSuffix(" Ω")

        self.rl = QDoubleSpinBox()
        self.rl.setRange(1, 1_000_000)
        self.rl.setValue(10000)
        self.rl.setSuffix(" Ω")

        dut_form.addRow("Chip Name:", self.chip_name)
        dut_form.addRow("V+ Supply:", self.vplus)
        dut_form.addRow("V- Supply:", self.vminus)
        dut_form.addRow("Rf Feedback Resistor:", self.rf)
        dut_form.addRow("Rg Input/Ground Resistor:", self.rg)
        dut_form.addRow("Output Load Resistance:", self.rl)

        dut_group.setLayout(dut_form)

        test_group = QGroupBox("Test Settings")
        test_form = QFormLayout()

        self.vin_sweep = QLineEdit("0, 0.1, 0.2, 0.3, 0.4, 0.5")

        self.gain_tol = QDoubleSpinBox()
        self.gain_tol.setRange(0.1, 100)
        self.gain_tol.setValue(5.0)
        self.gain_tol.setSuffix(" %")

        self.zero_tol = QDoubleSpinBox()
        self.zero_tol.setRange(0.001, 1)
        self.zero_tol.setValue(0.05)
        self.zero_tol.setSuffix(" V")

        self.smu_current_limit = QDoubleSpinBox()
        self.smu_current_limit.setRange(0.000001, 1)
        self.smu_current_limit.setDecimals(6)
        self.smu_current_limit.setValue(0.005)
        self.smu_current_limit.setSuffix(" A")

        self.psu_current_limit = QDoubleSpinBox()
        self.psu_current_limit.setRange(0.001, 1)
        self.psu_current_limit.setDecimals(4)
        self.psu_current_limit.setValue(0.100)
        self.psu_current_limit.setSuffix(" A")

        self.sample_count = QSpinBox()
        self.sample_count.setRange(1, 100)
        self.sample_count.setValue(30)

        self.settling_time = QDoubleSpinBox()
        self.settling_time.setRange(0.01, 10)
        self.settling_time.setValue(0.05)
        self.settling_time.setSuffix(" s")

        test_form.addRow("Vin Sweep Values:", self.vin_sweep)
        test_form.addRow("Gain Tolerance:", self.gain_tol)
        test_form.addRow("Zero Input Vout Limit:", self.zero_tol)
        test_form.addRow("SMU Current Limit:", self.smu_current_limit)
        test_form.addRow("PSU Current Limit:", self.psu_current_limit)
        test_form.addRow("Samples per Point:", self.sample_count)
        test_form.addRow("Settling Time:", self.settling_time)

        test_group.setLayout(test_form)

        top_layout = QHBoxLayout()
        top_layout.addWidget(instrument_group)
        top_layout.addWidget(dut_group)
        top_layout.addWidget(test_group)
        main_layout.addLayout(top_layout)

        self.gain_label = QLabel()
        self.update_gain_label()
        self.rf.valueChanged.connect(self.update_gain_label)
        self.rg.valueChanged.connect(self.update_gain_label)

        main_layout.addWidget(self.gain_label)

        button_layout = QHBoxLayout()

        self.run_button = QPushButton("Run Basic Functionality Test")
        self.run_button.clicked.connect(self.run_test)

        self.clear_button = QPushButton("Clear Results")
        self.clear_button.clicked.connect(self.clear_results)

        button_layout.addWidget(self.run_button)
        button_layout.addWidget(self.clear_button)
        main_layout.addLayout(button_layout)

        self.status_box = QLabel("Status: Ready")
        self.status_box.setAlignment(Qt.AlignCenter)
        self.status_box.setStyleSheet(
            "background-color: lightgray; font-size: 16px; padding: 8px;"
        )
        main_layout.addWidget(self.status_box)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Vin (V)",
            "Vout Avg (V)",
            "Vout Std (V)",
            "Expected Vout (V)",
            "Expected Gain",
            "Measured Gain",
            "Gain Error (%)",
            "Result"
        ])
        main_layout.addWidget(self.table)

        self.setLayout(main_layout)

    def update_gain_label(self):
        gain = 1.0 + self.rf.value() / self.rg.value()
        self.gain_label.setText(
            f"Calculated Non-Inverting Gain: Av = 1 + Rf/Rg = {gain:.4f} V/V "
            f"| DMM digits default = {DMM_DIGITS_DEFAULT}"
        )

    def collect_settings(self):
        return {
            "chip_name": self.chip_name.text().strip(),
            "psu_resource": self.psu_resource.text().strip(),
            "smu_resource": self.smu_resource.text().strip(),
            "dmm_resource": self.dmm_resource.text().strip(),
            "psu_pos_ch": self.psu_pos_ch.text().strip(),
            "psu_neg_ch": self.psu_neg_ch.text().strip(),

            "vplus": self.vplus.value(),
            "vminus": self.vminus.value(),

            "rf": self.rf.value(),
            "rg": self.rg.value(),
            "rl": self.rl.value(),

            "vin_sweep": self.vin_sweep.text().strip(),

            "gain_tolerance_percent": self.gain_tol.value(),
            "zero_tolerance": self.zero_tol.value(),

            "smu_current_limit": self.smu_current_limit.value(),
            "psu_current_limit": self.psu_current_limit.value(),

            "sample_count": self.sample_count.value(),
            "settling_time": self.settling_time.value(),

            "initial_delay": 0.5,
            "dmm_range": 10.0,
            "dmm_timeout": 1.0,
        }

    def run_test(self):
        try:
            settings = self.collect_settings()
            parse_sweep(settings["vin_sweep"])
        except Exception as e:
            QMessageBox.critical(self, "Input Error", str(e))
            return

        self.run_button.setEnabled(False)
        self.status_box.setText("Status: Running...")
        self.status_box.setStyleSheet(
            "background-color: yellow; font-size: 16px; padding: 8px;"
        )

        self.worker = FunctionalityWorker(settings)
        self.worker.result_signal.connect(self.add_result)
        self.worker.status_signal.connect(self.update_status)
        self.worker.finished_signal.connect(self.test_finished)
        self.worker.start()

    def add_result(self, result):
        row = self.table.rowCount()
        self.table.insertRow(row)

        values = [
            f"{result['vin']:.6f}",
            f"{result['vout']:.6f}",
            f"{result['vout_std']:.6f}",
            f"{result['expected_vout']:.6f}",
            f"{result['expected_gain']:.4f}",
            "N/A" if np.isnan(result["measured_gain"]) else f"{result['measured_gain']:.4f}",
            "N/A" if np.isnan(result["gain_error_percent"]) else f"{result['gain_error_percent']:.3f}",
            "PASS" if result["passed"] else "FAIL"
        ]

        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)

            if col == 7:
                item.setBackground(Qt.green if result["passed"] else Qt.red)

            self.table.setItem(row, col, item)

    def update_status(self, message):
        self.status_box.setText(f"Status: {message}")

    def test_finished(self, passed, message):
        self.run_button.setEnabled(True)
        self.status_box.setText(message)

        if passed:
            self.status_box.setStyleSheet(
                "background-color: lightgreen; font-size: 16px; padding: 8px;"
            )
        else:
            self.status_box.setStyleSheet(
                "background-color: red; color: white; font-size: 16px; padding: 8px;"
            )

    def clear_results(self):
        self.table.setRowCount(0)
        self.status_box.setText("Status: Ready")
        self.status_box.setStyleSheet(
            "background-color: lightgray; font-size: 16px; padding: 8px;"
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = FunctionalityGUI()
    gui.show()
    sys.exit(app.exec())