import nidcpower
import numpy as np

with nidcpower.Session(resource_name='SMU') as session:
    session.source_mode = nidcpower.SourceMode.CURRENT 
    session.voltage_limit = 1.0 #prevents damage to smu
    session.measure_record_length = 30 #samples
    session.measure_record_length_is_finite = True
    session.measure_when = nidcpower.MeasureWhen.AUTOMATICALLY_AFTER_SOURCE_COMPLETE #measures after source is applied
    session.current_level = 0.000100 #100uA

    session.commit() #applies these values

    print('Starting measurement')

    voltages_all = [] #list to store values

    with session.initiate():
        channels = session.get_channel_names('0-{}'.format(session.channel_count - 1)) #takes the names of the channels, 1 in our case
        for channel_name in channels:
            while len(voltages_all) < session.measure_record_length: # mientras samples <30, keep taking samples
                measurements = session.channels[channel_name].fetch_multiple(count=session.fetch_backlog)
                voltages_all.extend([m.voltage for m in measurements]) #add voltages a la lista

    voltages = voltages_all[:30]
    avg_voltage = np.mean(voltages)

    print(f"Average Voltage: {avg_voltage:.6f} V")

    # Check pass/fail
    if 0.7 <= avg_voltage < 0.75:
        print("Test PASS: Voltage within threshold")
    else:
        print("Test FAIL: Voltage out of threshold")

# Cambiar correinte hasta que llegue al nivel deseado de voltaje
# Luego, obtener los 30 samples requeridos
# Add check cases (si se excede mucho el voltaje, o si nunca llega, fail test)