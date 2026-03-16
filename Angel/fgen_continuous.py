import nifgen
import sys
from enum import Enum

# --- Helper to get a single key press ---
if sys.platform == "win32":
    import msvcrt
    def get_key():
        return msvcrt.getch().decode("utf-8")
else:
    import tty, termios
    def get_key():
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch
# ----------------------------------------

MAX_VP = 12.0  # PXIe-5413 maximum amplitude
RESOURCE_NAME = "Func_Gen"  # Replace with your PXIe-5413 resource string

# --- Enum for waveforms ---
class MyWaveform(Enum):
    SINE = nifgen.Waveform.SINE
    SQUARE = nifgen.Waveform.SQUARE
    TRIANGLE = nifgen.Waveform.TRIANGLE

# --- Functions ---
def configure_waveform(session, waveform_enum, freq, amp):
    """Configure waveform using custom enum."""
    if amp > MAX_VP:
        print(f"Amplitude {amp} Vp exceeds max {MAX_VP} V. Cannot configure.")
        return False

    session.configure_standard_waveform(
        waveform=waveform_enum.value,  # use .value for NI-FGEN
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
    """Ask user for frequency and amplitude, enforce limits."""
    try:
        freq = float(input("Enter frequency in Hz (e.g., 1e6 for 1 MHz): "))

        while True:
            amp = float(input(f"Enter amplitude in Vp (max {MAX_VP} V): "))
            if amp <= MAX_VP:
                break
            else:
                print(f"Amplitude {amp} Vp exceeds max {MAX_VP} V. Try again.")
    except ValueError:
        print("Invalid input, using defaults: 1 MHz, 1 Vp")
        freq, amp = 1e6, 1.0
    return freq, amp

# --- Main program ---
with nifgen.Session(RESOURCE_NAME) as session:
    freq, amp = get_user_settings()
    print(f"freq and amp: {freq}, {amp}")
    current_waveform = MyWaveform.SINE
    configure_waveform(session, current_waveform, freq, amp)

    print("\nWaveform running...")
    print("Press 1=Sine, 2=Triangle, 3=Square, c=Reconfigure, i=Stop")

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

        # ignore other keys


    # Stop waveform at the end
    session.abort()

print("Generation stopped.")
