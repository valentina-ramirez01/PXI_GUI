import sys
import time
import numpy as np

import nidcpower
import nifgen
import niscope

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit,
    QDoubleSpinBox, QSpinBox, QVBoxLayout, QHBoxLayout,
    QFormLayout, QTableWidget, QTableWidgetItem, QMessageBox,
    QGroupBox
)


def parse_sweep(text):
    values = []
    for item in text.split(","):
        item = item.strip()
        if item:
            values.append(float(item))
    return values


def vpp_from_waveform(y):
    y = np.asarray(y, dtype=float)
    return float(np.max(y) - np.min(y))


class ACFunctionalityWorker(QThread):
    result_signal = Signal(dict)
    status_signal = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, settings):
        super().__init__()
        self.s = settings

    def run(self):
        psu = None
        fg = None
        scope = None

        try:
            chip = self.s["chip_name"]

            rf = self.s["rf"]
            rg = self.s["rg"]
            expected_gain = 1.0 + rf / rg

            vin_vpp = self.s["vin_vpp"]
            expected_vout_vpp = expected_gain * vin_vpp

            freqs = parse_sweep(self.s["freq_sweep"])

            low_freq_gain = None
            first_fail_freq = None
            all_pass = True

            self.status_signal.emit("Opening instrument sessions...")

            psu = nidcpower.Session(self.s["psu_resource"])
            fg = nifgen.Session(self.s["fg_resource"])
            scope = niscope.Session(self.s["scope_resource"])

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
            time.sleep(self.s["initial_delay"])

            self.status_signal.emit("Configuring function generator...")

            fg.output_mode = nifgen.OutputMode.FUNC
            fg.configure_standard_waveform(
                waveform=nifgen.Waveform.SINE,
                amplitude=vin_vpp,
                dc_offset=0.0,
                frequency=freqs[0],
                start_phase=0.0
            )

            try:
                fg.output_impedance = 50.0
            except Exception:
                pass

            fg.output_enabled = True
            fg.initiate()

            self.status_signal.emit("Configuring oscilloscope...")

            scope_chan = self.s["scope_channel"]


            scope.channels[scope_chan].vertical_range = self.s["scope_range"]
            scope.channels[scope_chan].vertical_coupling = niscope.VerticalCoupling.DC
            scope.channels[scope_chan].probe_attenuation = 1.0
            scope.channels[scope_chan].enabled = True
            scope.configure_trigger_immediate()

            for freq in freqs:
                self.status_signal.emit(f"Testing {freq:g} Hz...")

                fg.configure_standard_waveform(
                    waveform=nifgen.Waveform.SINE,
                    amplitude=vin_vpp,
                    dc_offset=0.0,
                    frequency=freq,
                    start_phase=0.0
                )

                time.sleep(self.s["settling_time"])

                sample_rate = max(
                    self.s["min_sample_rate"],
                    freq * self.s["samples_per_cycle"]
                )

                record_length = int(
                    max(
                        self.s["min_record_length"],
                        self.s["cycles_to_capture"] * sample_rate / freq
                    )
                )

                scope.configure_horizontal_timing(
                    min_sample_rate=sample_rate,
                    min_num_pts=record_length,
                    ref_position=50.0,
                    num_records=1,
                    enforce_realtime=True
                )

                with scope.initiate():
                    waveform = scope.channels[scope_chan].fetch(
                        timeout=self.s["scope_timeout"]
                    )

                y = np.array(waveform.samples, dtype=float)

                # Remove DC offset before checking distortion/noise behavior
                y_ac = y - np.mean(y)

                measured_vout_vpp = vpp_from_waveform(y_ac)
                measured_gain = measured_vout_vpp / vin_vpp

                if low_freq_gain is None:
                    low_freq_gain = measured_gain

                gain_db_relative = 20.0 * np.log10(
                    measured_gain / low_freq_gain
                ) if measured_gain > 0 and low_freq_gain > 0 else -999.0

                gain_error_percent = abs(
                    (measured_gain - expected_gain) / expected_gain
                ) * 100.0

                max_vout_allowed = min(
                    abs(self.s["vplus"]),
                    abs(self.s["vminus"])
                ) - self.s["rail_margin"]

                clipping = (measured_vout_vpp / 2.0) >= max_vout_allowed

                gain_pass = gain_error_percent <= self.s["gain_tolerance_percent"]
                bandwidth_pass = gain_db_relative >= -3.0
                clip_pass = not clipping

                passed = gain_pass and bandwidth_pass and clip_pass

                if not passed:
                    all_pass = False
                    if first_fail_freq is None:
                        first_fail_freq = freq

                self.result_signal.emit({
                    "freq": freq,
                    "vin_vpp": vin_vpp,
                    "vout_vpp": measured_vout_vpp,
                    "expected_vout_vpp": expected_vout_vpp,
                    "expected_gain": expected_gain,
                    "measured_gain": measured_gain,
                    "gain_error_percent": gain_error_percent,
                    "relative_db": gain_db_relative,
                    "clipping": clipping,
                    "passed": passed
                })

            fg.output_enabled = False

            if all_pass:
                final_msg = (
                    f"PASS: {chip} passed AC closed-loop functionality test. "
                    f"No failure detected in sweep."
                )
            else:
                final_msg = (
                    f"FAIL: {chip} first failed at approximately "
                    f"{first_fail_freq:g} Hz."
                )

            self.finished_signal.emit(all_pass, final_msg)

        except Exception as e:
            self.finished_signal.emit(False, f"TEST ERROR: {e}")

        finally:
            try:
                if fg:
                    fg.output_enabled = False
                    fg.close()
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
                if scope:
                    scope.close()
            except:
                pass


class ACFunctionalityGUI(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("OPA551 AC Functionality / Frequency Failure Test")
        self.resize(1400, 750)

        self.worker = None

        main_layout = QVBoxLayout()

        instrument_group = QGroupBox("Instrument Resource Names")
        instrument_form = QFormLayout()

        self.psu_resource = QLineEdit("PXI4110")
        self.fg_resource = QLineEdit("Func_Gen")
        self.scope_resource = QLineEdit("Scope")
        self.psu_pos_ch = QLineEdit("1")
        self.psu_neg_ch = QLineEdit("2")
        self.scope_channel = QLineEdit("0")

        instrument_form.addRow("PXI-4110 Resource:", self.psu_resource)
        instrument_form.addRow("PXIe-5413 FGEN Resource:", self.fg_resource)
        instrument_form.addRow("PXIe-5114 Scope Resource:", self.scope_resource)
        instrument_form.addRow("+15 V PSU Channel:", self.psu_pos_ch)
        instrument_form.addRow("-15 V PSU Channel:", self.psu_neg_ch)
        instrument_form.addRow("Scope Vout Channel:", self.scope_channel)

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
        self.rf.setDecimals(2)
        self.rf.setValue(10000.0)
        self.rf.setSuffix(" Ω")

        self.rg = QDoubleSpinBox()
        self.rg.setRange(1, 1_000_000)
        self.rg.setDecimals(2)
        self.rg.setValue(1000.0)
        self.rg.setSuffix(" Ω")

        self.rl = QDoubleSpinBox()
        self.rl.setRange(1, 1_000_000)
        self.rl.setValue(3000.0)
        self.rl.setSuffix(" Ω")

        dut_form.addRow("Chip Name:", self.chip_name)
        dut_form.addRow("V+ Supply:", self.vplus)
        dut_form.addRow("V- Supply:", self.vminus)
        dut_form.addRow("Rf Feedback Resistor:", self.rf)
        dut_form.addRow("Rg Ground Resistor:", self.rg)
        dut_form.addRow("Output Load Resistance:", self.rl)

        dut_group.setLayout(dut_form)

        test_group = QGroupBox("AC Test Settings")
        test_form = QFormLayout()

        self.vin_vpp = QDoubleSpinBox()
        self.vin_vpp.setRange(0.001, 10.0)
        self.vin_vpp.setDecimals(4)
        self.vin_vpp.setValue(0.1000)
        self.vin_vpp.setSuffix(" Vpp")

        self.freq_sweep = QLineEdit(
            "10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000, 300000, 1000000"
        )

        self.gain_tol = QDoubleSpinBox()
        self.gain_tol.setRange(0.1, 100)
        self.gain_tol.setValue(10.0)
        self.gain_tol.setSuffix(" %")

        self.scope_range = QDoubleSpinBox()
        self.scope_range.setRange(0.1, 40.0)
        self.scope_range.setValue(5.0)
        self.scope_range.setSuffix(" V")

        self.psu_current_limit = QDoubleSpinBox()
        self.psu_current_limit.setRange(0.001, 1.0)
        self.psu_current_limit.setDecimals(4)
        self.psu_current_limit.setValue(0.100)
        self.psu_current_limit.setSuffix(" A")

        self.samples_per_cycle = QSpinBox()
        self.samples_per_cycle.setRange(20, 5000)
        self.samples_per_cycle.setValue(200)

        self.cycles_to_capture = QSpinBox()
        self.cycles_to_capture.setRange(2, 100)
        self.cycles_to_capture.setValue(10)

        self.settling_time = QDoubleSpinBox()
        self.settling_time.setRange(0.01, 5.0)
        self.settling_time.setValue(0.10)
        self.settling_time.setSuffix(" s")

        test_form.addRow("Programmed Vin:", self.vin_vpp)
        test_form.addRow("Frequency Sweep:", self.freq_sweep)
        test_form.addRow("Gain Error Limit:", self.gain_tol)
        test_form.addRow("Scope Vertical Range:", self.scope_range)
        test_form.addRow("PSU Current Limit:", self.psu_current_limit)
        test_form.addRow("Samples per Cycle:", self.samples_per_cycle)
        test_form.addRow("Cycles Captured:", self.cycles_to_capture)
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
        self.vin_vpp.valueChanged.connect(self.update_gain_label)

        main_layout.addWidget(self.gain_label)

        button_layout = QHBoxLayout()

        self.run_button = QPushButton("Run AC Functionality Sweep")
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
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "Freq (Hz)",
            "Vin Prog (Vpp)",
            "Vout Meas (Vpp)",
            "Expected Vout (Vpp)",
            "Expected Gain",
            "Measured Gain",
            "Gain Error (%)",
            "Rel Gain (dB)",
            "Clip?",
            "Result"
        ])

        main_layout.addWidget(self.table)
        self.setLayout(main_layout)

    def update_gain_label(self):
        gain = 1.0 + self.rf.value() / self.rg.value()
        expected_vout = gain * self.vin_vpp.value()

        self.gain_label.setText(
            f"Calculated Non-Inverting Gain: Av = {gain:.4f} V/V | "
            f"Programmed Vin = {self.vin_vpp.value():.4f} Vpp | "
            f"Expected Vout = {expected_vout:.4f} Vpp"
        )

    def collect_settings(self):
        return {
            "chip_name": self.chip_name.text().strip(),

            "psu_resource": self.psu_resource.text().strip(),
            "fg_resource": self.fg_resource.text().strip(),
            "scope_resource": self.scope_resource.text().strip(),

            "psu_pos_ch": self.psu_pos_ch.text().strip(),
            "psu_neg_ch": self.psu_neg_ch.text().strip(),
            "scope_channel": self.scope_channel.text().strip(),

            "vplus": self.vplus.value(),
            "vminus": self.vminus.value(),

            "rf": self.rf.value(),
            "rg": self.rg.value(),
            "rl": self.rl.value(),

            "vin_vpp": self.vin_vpp.value(),
            "freq_sweep": self.freq_sweep.text().strip(),

            "gain_tolerance_percent": self.gain_tol.value(),
            "scope_range": self.scope_range.value(),
            "psu_current_limit": self.psu_current_limit.value(),

            "samples_per_cycle": self.samples_per_cycle.value(),
            "cycles_to_capture": self.cycles_to_capture.value(),
            "settling_time": self.settling_time.value(),

            "initial_delay": 0.5,
            "scope_timeout": 5.0,
            "min_sample_rate": 100_000.0,
            "min_record_length": 2000,
            "rail_margin": 1.5,
        }

    def run_test(self):
        try:
            settings = self.collect_settings()
            parse_sweep(settings["freq_sweep"])
        except Exception as e:
            QMessageBox.critical(self, "Input Error", str(e))
            return

        self.run_button.setEnabled(False)
        self.status_box.setText("Status: Running...")
        self.status_box.setStyleSheet(
            "background-color: yellow; font-size: 16px; padding: 8px;"
        )

        self.worker = ACFunctionalityWorker(settings)
        self.worker.result_signal.connect(self.add_result)
        self.worker.status_signal.connect(self.update_status)
        self.worker.finished_signal.connect(self.test_finished)
        self.worker.start()

    def add_result(self, result):
        row = self.table.rowCount()
        self.table.insertRow(row)

        values = [
            f"{result['freq']:.3f}",
            f"{result['vin_vpp']:.6f}",
            f"{result['vout_vpp']:.6f}",
            f"{result['expected_vout_vpp']:.6f}",
            f"{result['expected_gain']:.4f}",
            f"{result['measured_gain']:.4f}",
            f"{result['gain_error_percent']:.3f}",
            f"{result['relative_db']:.3f}",
            "YES" if result["clipping"] else "NO",
            "PASS" if result["passed"] else "FAIL"
        ]

        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)

            if col == 9:
                item.setBackground(Qt.green if result["passed"] else Qt.red)

            if col == 8 and result["clipping"]:
                item.setBackground(Qt.red)

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
    gui = ACFunctionalityGUI()
    gui.show()
    sys.exit(app.exec())