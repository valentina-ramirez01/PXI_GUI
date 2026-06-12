        pss_v_per_v = abs(slope)
        pss_uv_per_v = pss_v_per_v * 1e6
        pss_db = 20 * math.log10(pss_v_per_v) if pss_v_per_v > 0 else float("-inf")

        return {
            "supply": supply_values,
            "vout_avg": vout_avg,
            "vout_std": vout_std,
            "slope": slope,
            "intercept": intercept,
            "pss_uv_per_v": pss_uv_per_v,
            "pss_db": pss_db,
        }

    finally:
        try:
            if smu_pos:
                smu_pos.voltage_level = 0
                smu_pos.output_enabled = False
                smu_pos.close()
        except:
            pass

        try:
            if smu_neg:
                smu_neg.voltage_level = 0
                smu_neg.output_enabled = False
                smu_neg.close()
        except:
            pass

        try:
            if dmm:
                dmm.close()
        except:
            pass