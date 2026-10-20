#!/usr/bin/env python3
# Longitudinal per-vehicle tune accessors.
# Seeded with the far-lead coast headway floor used by the lead_behavior
# contract tests; the full per-vehicle tune surface lands with the
# latcontrol_vehicle_tunes port (P1). Only ever *relaxes* the coast gate.
GM_SILVERADO_FAR_LEAD_COAST_HEADWAY_FLOOR = 1.25


def get_far_lead_coast_headway_floor(CP):
  if (
    getattr(CP, "brand", "") == "gm" and
    str(getattr(CP, "carFingerprint", "")) in ("CHEVROLET_SILVERADO", "CHEVROLET_SILVERADO_CC") and
    not bool(getattr(CP, "enableGasInterceptorDEPRECATED", False))
  ):
    return GM_SILVERADO_FAR_LEAD_COAST_HEADWAY_FLOOR
  return 1.75
