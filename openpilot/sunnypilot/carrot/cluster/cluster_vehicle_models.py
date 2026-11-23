#!/usr/bin/env python3
# Copyright (c) 2026, firestar5683 and StarPilot contributors
# SPDX-License-Identifier: MIT
"""Display-only model selection from the detected CarParams fingerprint.

Data/resource mapping ported from CarrotPilot's
selfdrive/carrot/cluster/cluster_vehicle_models.py. Only the mapping is
ported: this fork's cluster renderer has no parked 3D vehicle pipeline
(the driving model is always the Cybertruck OBJ), so the mapping is kept
as pure data for a future consumer.

Note: this fork only ships assets/models/cybertruck; the ev6/others OBJ
families referenced below are not present, so any consumer must fall
back to the driving model or ship the assets first.
"""

# Explicit families avoid matching unrelated names (for example IONIQ 6).
EGO_MODEL_FINGERPRINTS = {
  "HYUNDAI_IONIQ_5": "ioniq5",
  "HYUNDAI_IONIQ_5_PE": "ioniq5",
  "HYUNDAI_IONIQ_5_N": "ioniq5",
  "HYUNDAI_STARIA_4TH_GEN": "staria",
  "HYUNDAI_STARIA_EV": "staria",
  "HYUNDAI_TUCSON_4TH_GEN": "tucson",
  "KIA_CARNIVAL_4TH_GEN": "carnival",
  "KIA_EV9": "ev9",
  "KIA_SPORTAGE_5TH_GEN": "sportage",
}


def ego_model_name(car_fingerprint: str) -> str:
  return EGO_MODEL_FINGERPRINTS.get(car_fingerprint, "ev6")
