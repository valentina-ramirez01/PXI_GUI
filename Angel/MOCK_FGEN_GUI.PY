import sys
from enum import Enum

# ============================================================
# MOCK NIFGEN MODE
# Set this to False only when you are connected to the PXIe-5413
# ============================================================
USE_MOCK = True

if USE_MOCK:
    class MockWaveform:
        SINE = "SINE"
        SQUARE = "SQUARE"
        TRIANGLE = "TRIANGLE"

    class MockOutputMode:
        FUNC = "FUNC"

    class MockSession:
        def __init__(self, resource_name):
            self.resource_name = resource_name
            self.output_mode = None

        def __enter__(self):
            print(f"[MOCK] Connected to {self.resource_name}")
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            print("[MOCK] Session closed")

        def configure_standard_waveform(
            self,
            waveform,
            amplitude,
            frequency,
            dc_offset,
            start_phase
        ):
            print("\n[MOCK] configure_standard_waveform called")
            print(f"Waveform:   {waveform}")
            print(f"Frequency:  {frequency} Hz")
            print(f"Amplitude:  {amplitude} Vp")
            print(f"DC Offset:  {dc_offset} V")
            print(f"Phase:      {start_phase} deg")

        def initiate(self):
            print("[MOCK] Generation initiated")

        def abort(self):
            print("[MOCK] Generation stopped")

    class nifgen:
        Session = MockSession
        Waveform = MockWaveform
        OutputMode = MockOutputMode

else:
    import nifgen


# ============================================================
# Helper to get a single key press
# ============================================================
if sys.platform == "win32":
    import msvcrt

    def get_key():
        return msvcrt.getch().decode("utf-8")

else:
    import tty
    import termios

    def get_key():
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch


# ============================================================
# Constants
# ============================================================
MAX_VP = 12.0
RESOURCE_NAME = "Func_Gen"


# ============================================================
# Enum for waveforms
# ============================================================
class MyWaveform(Enum):
    SINE = nifgen.Waveform.SINE
    SQUARE = nifgen.Waveform.SQUARE
    TRIANGLE = nifgen.Waveform.TRIANGLE


# ============================================================
# Functions
# ============================================================
def configure_waveform(session, waveform_enum, freq, amp):
    if amp > MAX_VP:
        print(f"Amplitude {amp} Vp exceeds max {MAX_VP} V. Cannot configure.")
        return False

    session.configure_standard_waveform(
        waveform=waveform_enum.value,
        amplitude=amp,
        frequency=freq,
        dc_offset=0.0,
        start_phase=0.0
    )

    session.output_mode = nifgen.OutputMode.FUNC
    session.initiate()

    print(f"→ {waveform_enum.name} at {freq} Hz, {amp} Vp")
    return True


def get_user_settings():
    try:
        freq = float(input("Enter frequency in Hz, example 1e6 for 1 MHz: "))

        while True:
            amp = float(input(f"Enter amplitude in Vp, max {MAX_VP} V: "))
            if amp <= MAX_VP:
                break
            else:
                print(f"Amplitude {amp} Vp exceeds max {MAX_VP} V. Try again.")

    except ValueError:
        print("Invalid input, using defaults: 1 MHz, 1 Vp")
        freq = 1e6
        amp = 1.0

    return freq, amp


# ============================================================
# Main program
# ============================================================
with nifgen.Session(RESOURCE_NAME) as session:
    freq, amp = get_user_settings()

    print(f"\nfreq and amp: {freq}, {amp}")

    current_waveform = MyWaveform.SINE
    configure_waveform(session, current_waveform, freq, amp)

    print("\nWaveform running...")
    print("Press 1 = Sine")
    print("Press 2 = Triangle")
    print("Press 3 = Square")
    print("Press c = Reconfigure")
    print("Press i = Stop")

    while True:
        key = get_key()
        k = key.lower()

        if k == "1":
            current_waveform = MyWaveform.SINE
            configure_waveform(session, current_waveform, freq, amp)

        elif k == "2":
            current_waveform = MyWaveform.TRIANGLE
            configure_waveform(session, current_waveform, freq, amp)

        elif k == "3":
            current_waveform = MyWaveform.SQUARE
            configure_waveform(session, current_waveform, freq, amp)

        elif k == "c":
            print("\n--- Reconfigure waveform ---")
            freq, amp = get_user_settings()
            configure_waveform(session, current_waveform, freq, amp)

        elif k == "i":
            print("Key 'i' pressed → stopping generation.")
            break

    session.abort()

print("Generation stopped.")