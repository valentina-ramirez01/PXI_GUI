#!/usr/bin/env python
# -- coding: utf-8 --

import time
import nifgen
import niscope
import nidcpower
import numpy as np
import statistics

# --- HARDWARE RESOURCES ---
RESOURCE_PS    = "PXI4110"
RESOURCE_AWG   = "Func_Gen"
RESOURCE_SCOPE = "Scope"

# --- TEST CONSTANTS ---
NUM_RUNS = 30
SAMPLE_RATE = 100e6
READ_TIMEOUT = 5.0 # Seconds

def main():
    print("==================================================")
    print("  OPA551 SLEW RATE CHARACTERIZATION               ")
    print("==================================================")
    
    slew_rate_results = []
    
    try:
        with nidcpower.Session(RESOURCE_PS, channels="1,2") as ps, \
             nifgen.Session(RESOURCE_AWG) as fgen, \
             niscope.Session(RESOURCE_SCOPE) as scope:
            
            # Setup Power Rails
            ps.channels[1].voltage_level = 15.0
            ps.channels[2].voltage_level = -15.0
            ps.channels["1,2"].output_enabled = True
            ps.initiate()
            
            # AWG Config
            fgen.output_mode = nifgen.OutputMode.FUNC
            fgen.configure_standard_waveform(
                waveform=nifgen.Waveform.SQUARE,
                amplitude=10.0,
                frequency=10e3,
                dc_offset=0.0
            )
            fgen.initiate()
            
            # Scope Config
            chan = scope.channels["0"]
            chan.vertical_range = 5.0
            chan.vertical_coupling = niscope.VerticalCoupling.DC
            
            scope.configure_horizontal_timing(SAMPLE_RATE, 1000, 50.0, 1, True)
            
            # Trigger setup
            scope.trigger_source = "0"
            scope.trigger_level = 0.0 
            scope.trigger_coupling = niscope.TriggerCoupling.DC
            scope.trigger_slope = niscope.TriggerSlope.POSITIVE
            
            # Loop until we hit exactly 30 successful captures
            while len(slew_rate_results) < NUM_RUNS:
                try:
                    waveform_info_list = chan.read(num_samples=1000, timeout=READ_TIMEOUT)
                    waveform_data = waveform_info_list[0].samples
                    
                    v_max = np.max(waveform_data)
                    v_min = np.min(waveform_data)
                    v_10 = v_min + 0.1 * (v_max - v_min)
                    v_90 = v_min + 0.9 * (v_max - v_min)
                    
                    rising_indices = np.where((waveform_data > v_10) & (waveform_data < v_90))[0]
                    
                    if len(rising_indices) > 1:
                        dt = (rising_indices[-1] - rising_indices[0]) * (1.0 / SAMPLE_RATE)
                        if dt > 0:
                            sr_v_us = ((v_90 - v_10) / dt) / 1e6
                            slew_rate_results.append(sr_v_us)
                            print(f"Run {len(slew_rate_results):02d}: {sr_v_us:6.2f} V/µs")
                    
                    time.sleep(0.1)
                
                except Exception:
                    # Silently ignore timeouts/trigger misses to keep output clean
                    continue
            
            # Cleanup
            ps.channels["1,2"].output_enabled = False
            
            # Final Report
            print("\n" + "="*50)
            print(f"MEDIAN SLEW RATE : {statistics.median(slew_rate_results):.2f} V/µs")
            print(f"STDEV            : {statistics.stdev(slew_rate_results):.3f} V/µs")
            print("="*50)

    except Exception as e:
        print(f"\nExecution Error: {e}")
if __name__ == "__main__":
    main()