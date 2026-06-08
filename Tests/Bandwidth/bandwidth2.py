"""
OPA551 Bandwidth Test

DUT: OPA551
Power Supply: NI PXI-4110
Function Generator: NI PXIe-5413
Oscilloscope: NI PXIe-5114

Purpose:
Sweep sine-wave frequency, measure VIN and VOUT,
calculate gain, find the -3 dB bandwidth, and compare to expected value.
"""

import time
import math
import nidcpower
import nifgen
import niscope


PS_Name = "PXI4110"
Supply_Positive = 15.0
Supply_Negative = -15.0
Supply_Current_Limit = 0.050

FGEN_Name = "Func_Gen"
Scope_Input_Channel = "0"     # CH0 = IN+
Scope_Output_Channel = "1"    # CH1 = OUT

Input_Amplitude = 0.050       # Vpeak = 0.100 Vpp
Input_Offset = 0.0

SCOPE_Name = "Scope"
Sample_Rate = 10e6
Record_Length = 5000
Voltage_Range_Input = 0.5
Voltage_Range_Output = 2.0

RF = 10e3
RG = 1.1e3
EXPECTED_GAIN = 1 + (RF / RG)

GBW_TYP = 3e6
EXPECTED_BW = GBW_TYP / EXPECTED_GAIN
BW_TOLERANCE = 0.35

Frequency_List = [
    100, 300, 1000, 3000, 10000,
    30000, 50000, 100000, 200000,
    300000, 350000, 400000, 450000,
    500000, 700000, 1000000
]


def configure_op_amp_supplies(power_supply):
    power_supply.channels[1].voltage_level = Supply_Positive
    power_supply.channels[1].current_limit = Supply_Current_Limit
    power_supply.channels[1].output_enabled = True

    power_supply.channels[2].voltage_level = Supply_Negative
    power_supply.channels[2].current_limit = Supply_Current_Limit
    power_supply.channels[2].output_enabled = True


def disable_supplies(power_supply):
    try:
        power_supply.abort()
    except Exception:
        pass

    try:
        power_supply.channels[1].output_enabled = False
        power_supply.channels[2].output_enabled = False
    except Exception:
        pass


def configure_fgen(fgen, frequency):
    fgen.output_mode = nifgen.OutputMode.FUNC

    fgen.configure_standard_waveform(
        waveform=nifgen.Waveform.SINE,
        amplitude=Input_Amplitude,
        dc_offset=Input_Offset,
        frequency=frequency,
        start_phase=0.0
    )

    fgen.output_enabled = True


def disable_fgen(fgen):
    try:
        fgen.abort()
    except Exception:
        pass

    try:
        fgen.output_enabled = False
    except Exception:
        pass


def configure_scope(scope):
    scope.channels[Scope_Input_Channel].configure_vertical(
        range=Voltage_Range_Input,
        coupling=niscope.VerticalCoupling.DC,
        enabled=True
    )

    scope.channels[Scope_Output_Channel].configure_vertical(
        range=Voltage_Range_Output,
        coupling=niscope.VerticalCoupling.DC,
        enabled=True
    )

    scope.configure_horizontal_timing(
        min_sample_rate=Sample_Rate,
        min_num_pts=Record_Length,
        ref_position=50.0,
        num_records=1,
        enforce_realtime=False
    )

    scope.configure_trigger_edge(
        trigger_source=Scope_Input_Channel,
        level=0.0,
        trigger_coupling=niscope.TriggerCoupling.DC,
        slope=niscope.TriggerSlope.POSITIVE
    )


def waveform_to_samples(waveform):
    try:
        return list(waveform[0].samples)
    except Exception:
        try:
            return list(waveform.samples)
        except Exception:
            return list(waveform)


def calculate_vpp(samples):
    return max(samples) - min(samples)


def calculate_gain_db(vin_vpp, vout_vpp):
    if vin_vpp == 0:
        return 0.0, -999.0

    gain = vout_vpp / vin_vpp
    gain_db = 20 * math.log10(abs(gain))

    return gain, gain_db


def find_bandwidth(results):
    reference_gain_db = results[0]["gain_db"]
    target_gain_db = reference_gain_db - 3.0

    for item in results:
        if item["gain_db"] <= target_gain_db:
            return item["frequency"], target_gain_db, reference_gain_db

    return None, target_gain_db, reference_gain_db


def classify_bandwidth(measured_bw):
    lower_limit = EXPECTED_BW * (1 - BW_TOLERANCE)
    upper_limit = EXPECTED_BW * (1 + BW_TOLERANCE)

    if measured_bw is not None and lower_limit <= measured_bw <= upper_limit:
        return "PASS"
    else:
        return "CHECK / FAIL"


def main():
    print("=" * 90)
    print("OPA551 BANDWIDTH TEST")
    print("=" * 90)
    print("Required DUT connections:")
    print("OPA551 IN+   -> PXIe-5413 OUT and PXIe-5114 CH0")
    print("OPA551 IN-   -> RF to OUT and RG to GND")
    print("OPA551 OUT   -> RF to IN- and PXIe-5114 CH1")
    print("OPA551 V+    -> PXI-4110 CH1 = +15 V")
    print("OPA551 V-    -> PXI-4110 CH2 = -15 V")
    print("All grounds  -> common circuit GND")
    print("-" * 90)
    print(f"RF                : {RF:.0f} ohms")
    print(f"RG                : {RG:.0f} ohms")
    print(f"Expected gain     : {EXPECTED_GAIN:.2f} V/V")
    print(f"Expected gain     : {20 * math.log10(EXPECTED_GAIN):.2f} dB")
    print(f"Expected BW       : {EXPECTED_BW:.1f} Hz")
    print("=" * 90)

    input("Confirm wiring and press ENTER to start...")

    results = []

    with nidcpower.Session(resource_name=PS_Name, channels="1,2") as power_supply:
        try:
            configure_op_amp_supplies(power_supply)

            with power_supply.initiate():
                print("\n[+] Power supplies enabled.")
                time.sleep(1.0)

                with nifgen.Session(resource_name=FGEN_Name) as fgen:
                    try:
                        with niscope.Session(resource_name=SCOPE_Name) as scope:
                            configure_scope(scope)

                            for freq in Frequency_List:
                                print("\n" + "=" * 90)
                                print(f"Testing frequency: {freq:.1f} Hz")
                                print("=" * 90)

                                try:
                                    configure_fgen(fgen, freq)
                                    fgen.initiate()
                                    time.sleep(0.2)

                                    scope.initiate()

                                    input_waveform = scope.channels[Scope_Input_Channel].fetch(
                                        num_samples=Record_Length,
                                        timeout=5.0
                                    )

                                    output_waveform = scope.channels[Scope_Output_Channel].fetch(
                                        num_samples=Record_Length,
                                        timeout=5.0
                                    )

                                    vin_samples = waveform_to_samples(input_waveform)
                                    vout_samples = waveform_to_samples(output_waveform)

                                    vin_vpp = calculate_vpp(vin_samples)
                                    vout_vpp = calculate_vpp(vout_samples)

                                    gain, gain_db = calculate_gain_db(vin_vpp, vout_vpp)

                                    print(f"VIN Vpp       : {vin_vpp:.6f} V")
                                    print(f"VOUT Vpp      : {vout_vpp:.6f} V")
                                    print(f"Gain          : {gain:.4f} V/V")
                                    print(f"Gain          : {gain_db:.3f} dB")

                                    results.append({
                                        "frequency": freq,
                                        "vin_vpp": vin_vpp,
                                        "vout_vpp": vout_vpp,
                                        "gain": gain,
                                        "gain_db": gain_db
                                    })

                                finally:
                                    disable_fgen(fgen)
                                    print("[+] PXIe-5413 output disabled.")
                                    time.sleep(0.1)

                    finally:
                        disable_fgen(fgen)
                        print("[+] PXIe-5413 function generator disabled.")

        finally:
            disable_supplies(power_supply)
            print("\n[+] PXI-4110 outputs disabled.")

    bandwidth, target_gain_db, reference_gain_db = find_bandwidth(results)
    final_result = classify_bandwidth(bandwidth)

    lower_limit = EXPECTED_BW * (1 - BW_TOLERANCE)
    upper_limit = EXPECTED_BW * (1 + BW_TOLERANCE)

    print("\n" + "=" * 110)
    print("FINAL BANDWIDTH REPORT")
    print("=" * 110)
    print(f"| {'Freq (Hz)':<12} | {'VIN Vpp':<12} | {'VOUT Vpp':<12} | {'Gain':<12} | {'Gain dB':<12} |")
    print("-" * 110)

    for item in results:
        print(
            f"| {item['frequency']:<12.1f} | "
            f"{item['vin_vpp']:<12.6f} | "
            f"{item['vout_vpp']:<12.6f} | "
            f"{item['gain']:<12.4f} | "
            f"{item['gain_db']:<12.3f} |"
        )

    print("-" * 110)
    print(f"Reference gain        : {reference_gain_db:.3f} dB")
    print(f"-3 dB target gain     : {target_gain_db:.3f} dB")

    if bandwidth is not None:
        print(f"Measured bandwidth    : {bandwidth:.1f} Hz")
    else:
        print("Measured bandwidth    : Not found in sweep range")

    print(f"Expected bandwidth    : {EXPECTED_BW:.1f} Hz")
    print(f"Lower limit           : {lower_limit:.1f} Hz")
    print(f"Upper limit           : {upper_limit:.1f} Hz")
    print(f"Result                : {final_result}")
    print("=" * 110)


if __name__ == "__main__":
    main()