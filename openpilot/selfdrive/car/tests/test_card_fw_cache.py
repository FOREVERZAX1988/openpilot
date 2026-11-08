#!/usr/bin/env python3
"""Regression for the post-OTA LKAS fault on VAG MLB (2026-11-08 Macan).

CarParamsCache is CLEAR_ON_MANAGER_START, so every reboot -- and therefore every
OTA -- used to drop it and send card into a full VIN/FW UDS query. On MLB that
query reaches the EPS (0x712) during its ignition-on self-check and latches
EPS_HCA_Status=fault, which openpilot reports as "LKAS Fault: Restart Car to
Engage" until the car is power-cycled. card now reuses CarParamsPersistent for
VAG so fingerprint() takes its cached branch and skips the ECU query.
"""

import pytest

from opendbc.car.structs import car
from openpilot.selfdrive.car.card import cached_car_params_bytes


class FakeParams:
  def __init__(self, **values):
    self.values = values

  def get(self, key):
    return self.values.get(key)


def car_params(brand="volkswagen", vin="WP1AA2953FLB23826", fw_count=1):
  cp = car.CarParams.new_message()
  cp.brand = brand
  cp.carVin = vin
  if fw_count:
    cp.init("carFw", fw_count)
  return cp.to_bytes()


def test_in_boot_cache_wins():
  """A warm in-boot cache keeps stock behaviour, regardless of the persistent one."""
  cache = car_params()
  persistent = car_params(brand="toyota")
  assert cached_car_params_bytes(FakeParams(CarParamsCache=cache, CarParamsPersistent=persistent)) == cache


def test_vag_persistent_cache_skips_fw_query():
  persistent = car_params()
  assert cached_car_params_bytes(FakeParams(CarParamsPersistent=persistent)) == persistent


@pytest.mark.parametrize("brand,vin,fw_count", [
  ("toyota", "WP1AA2953FLB23826", 1),        # other brands keep stock behaviour
  ("volkswagen", "", 1),                      # no VIN
  ("volkswagen", "WP1AA2953FLB23826", 0),    # no ECU FW versions
])
def test_persistent_cache_not_trusted(brand, vin, fw_count):
  persistent = car_params(brand, vin, fw_count)
  assert cached_car_params_bytes(FakeParams(CarParamsPersistent=persistent)) is None


def test_no_cache_at_all():
  assert cached_car_params_bytes(FakeParams()) is None
