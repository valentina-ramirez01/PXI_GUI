import nidcpower

for name in ["PXI1Slot5", "PXI1Slot6"]:
    print("\nTrying:", name)
    try:
        with nidcpower.Session(name, reset=True) as smu:
            print("CONNECTED:", name)
            print("Instrument model:", smu.instrument_model)
    except Exception as e:
        print("FAILED:", name)
        print(type(e))
        print(e)