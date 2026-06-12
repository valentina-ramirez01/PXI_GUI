import time
import nidcpower
import nidmm

# =====================================
# RESOURCES
# =====================================

SMU_RESOURCE = "SMU1"
DMM_RESOURCE = "PXI4080"
PS_RESOURCE  = "PXI4110"

# =====================================
# CIRCUIT VALUES
# =====================================

RF = 10020.0
RG = 1000.0

EXPECTED_GAIN = 1 + (RF / RG)

# =====================================
# TEST VOLTAGES
# =====================================

VIN_VALUES = [
    -0.10,
    -0.05,
     0.00,
     0.05,
     0.10
]

# =====================================
# POWER SUPPLY
# =====================================

ps = nidcpower.Session(PS_RESOURCE, channels="1,2")

ps.channels["1"].voltage_level = 15.0
ps.channels["1"].current_limit = 0.05
ps.channels["1"].output_enabled = True

ps.channels["2"].voltage_level = -15.0
ps.channels["2"].current_limit = 0.05
ps.channels["2"].output_enabled = True

ps.initiate()

time.sleep(1)

# =====================================
# SMU
# =====================================

smu = nidcpower.Session(SMU_RESOURCE)

smu.output_function = nidcpower.OutputFunction.DC_VOLTAGE
smu.current_limit = 0.01
smu.voltage_level = 0.0
smu.output_enabled = True

smu.initiate()

# =====================================
# DMM
# =====================================

dmm = nidmm.Session(DMM_RESOURCE)

print()
print("=" * 70)
print("OPA551 DC GAIN TEST")
print("=" * 70)
print(f"RF = {RF:.1f} Ω")
print(f"RG = {RG:.1f} Ω")
print(f"Expected Gain = {EXPECTED_GAIN:.3f} V/V")
print("=" * 70)

for vin in VIN_VALUES:

    smu.voltage_level = vin

    time.sleep(0.3)

    vout = dmm.read()

    gain = vout / vin if abs(vin) > 1e-9 else float("nan")

    expected_vout = vin * EXPECTED_GAIN

    print(
        f"Vin={vin:+.3f} V | "
        f"Vout={vout:+.6f} V | "
        f"Expected={expected_vout:+.6f} V | "
        f"Gain={gain:.3f}"
    )

print("=" * 70)

# =====================================
# CLEANUP
# =====================================

smu.abort()
smu.output_enabled = False
smu.close()

ps.abort()
ps.channels["1"].output_enabled = False
ps.channels["2"].output_enabled = False
ps.close()

dmm.close()

print("Done.")