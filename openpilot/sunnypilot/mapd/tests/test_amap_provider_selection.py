"""Regression tests for Amap/OSM provider selection in mapd_manager.

Root cause of the "key entered while running never takes effect" bug:

  The OSM -> Amap hot-switch condition was

      if isinstance(live_map_sp, OsmMapData) and _amap_map_data_enabled() \\
          and _provider_has_key(live_map_sp):

  but ``_provider_has_key`` starts with ``isinstance(provider, AmapMapData)``,
  so while the live provider was the OSM one the condition was *always* False
  and the Amap provider could never be re-created after startup.

These tests pin the fixed semantics: the switch asks "is a key present?" and
never "does this OSM provider have a key?".
"""
import pathlib

from openpilot.common.params import Params
from openpilot.sunnypilot.mapd import mapd_manager


MAPD_MANAGER_SRC = pathlib.Path(mapd_manager.__file__).read_text(encoding="utf-8")


def test_amap_key_present_matches_param():
  """``_amap_key_present`` is a straight read of the AmapApiKey param."""
  assert mapd_manager._amap_key_present() == bool(Params().get("AmapApiKey"))


def test_provider_has_key_requires_amap_provider():
  """A non-Amap provider can never "have a key" - documents the old trap."""
  assert mapd_manager._provider_has_key(object()) is False


def test_osm_to_amap_switch_does_not_ask_the_osm_provider_for_a_key():
  """Guard against reintroducing the dead switch condition."""
  assert "and _provider_has_key(live_map_sp)" not in MAPD_MANAGER_SRC
  assert "and _amap_key_present()" in MAPD_MANAGER_SRC


def test_amap_fallback_has_a_grace_period_and_cooldown():
  """Give up only after a GPS-fix grace period, then retry instead of locking OSM."""
  assert mapd_manager.AMAP_HEALTH_GRACE_SEC >= 30.0
  assert mapd_manager.AMAP_RETRY_COOLDOWN_SEC >= mapd_manager.AMAP_HEALTH_GRACE_SEC
  # The fallback must be gated on a valid localizer, not on the first tick.
  assert "amap_grace_since" in MAPD_MANAGER_SRC
  assert "live_map_sp.localizer_valid" in MAPD_MANAGER_SRC
