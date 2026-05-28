import nidmm

print("nidmm imported")
print(nidmm.__version__)

session = nidmm.Session("PXI1Slot3", reset=True)
print("session opened")
session.close()
print("done")