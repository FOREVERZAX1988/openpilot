"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import datetime
import os
import platform
import threading
from time import monotonic

from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.selfdrive.ui.layouts.settings.software import time_ago
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.osm import MAP_PATH, delete_downloaded_maps
from openpilot.sunnypilot.mapd.china_provinces import CHINA_NATION_REF, CHINA_ALL_REF, CHINA_PROVINCES
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller

# Params the downloader keys off; wiping the maps without removing these would
# leave a half-finished region marked as present (re-imported from Big GUI osm.py).

MAP_SIZE_REFRESH_INTERVAL = 5.0  # seconds between map-size rescans


def _fmt_size(num_bytes: int) -> str:
  if num_bytes < 1024 ** 3:
    return f"{num_bytes / 1024 ** 2:.2f} {tr('MB')}"
  return f"{num_bytes / 1024 ** 3:.2f} {tr('GB')}"


def _calculate_map_size() -> int:
  total_size = 0
  directories_to_scan = [MAP_PATH] if MAP_PATH.exists() else []
  while directories_to_scan:
    try:
      for entry in os.scandir(directories_to_scan.pop()):
        if entry.is_file():
          total_size += entry.stat().st_size
        elif entry.is_dir():
          directories_to_scan.append(entry.path)
    except OSError:
      pass
  return total_size


def _fetch_locations(region_type: str, country: str) -> list[tuple[str, str]]:
  """(ref, display_name) list for a region picker; same sources as Big GUI."""
  if region_type == "State" and country == CHINA_NATION_REF:
    # Chinese provinces are not in pfeiferj/mapd's static state list; build the
    # picker from our embedded table so it works offline.
    provinces = sorted([(ref, name) for ref, name, _ in CHINA_PROVINCES], key=lambda x: x[1])
    return [(CHINA_ALL_REF, tr("All provinces"))] + provinces

  import requests
  base_url = "https://raw.githubusercontent.com/pfeiferj/openpilot-mapd/main/"
  url = base_url + ("nation_bounding_boxes.json" if region_type == "Country" else "us_states_bounding_boxes.json")
  try:
    data = requests.get(url, timeout=10).json()
    locations = sorted([(k, v['full_name']) for k, v in data.items()], key=lambda x: x[1])
  except Exception:
    locations = []

  if region_type == "State":
    locations.insert(0, ("All", tr("All states (~6.0 GB)")))
  return locations


class _RegionPickerPage(NavScroller):
  """Simple scrollable list picker; mici has no tree/search dialog, so the
  Big GUI TreeOptionDialog degrades to a flat BigButton list."""

  def __init__(self, title: str, locations: list[tuple[str, str]], current: str, on_select):
    super().__init__()
    self._scroller.add_widget(GreyBigButton(title, tr("scroll to continue")))
    for ref, name in locations:
      btn = BigButton(name, tr("selected") if ref == current else "")
      btn.set_click_callback(lambda r=ref, n=name: on_select(r, n))
      self._scroller.add_widget(btn)


class OSMLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else ui_state.params

    self._map_size = 0
    self._size_thread: threading.Thread | None = None
    self._last_size_update = 0.0
    self._pending_picker: tuple[str, str] | None = None  # (region_type, country) to open once data arrives

    self._mapd_version_btn = BigButton(tr("Mapd Version"), tr("Loading..."))
    self._mapd_version_btn.set_enabled(False)

    self._delete_maps_btn = BigButton(tr("Downloaded Maps"), tr("DELETE"),
                                      description=tr("This will delete ALL downloaded maps\n\nAre you sure you want to delete all maps?"))
    self._delete_maps_btn.set_click_callback(self._on_delete_maps)

    self._progress_btn = BigButton(tr("Downloading Maps"), "")
    self._progress_btn.set_enabled(False)

    self._update_db_btn = BigButton(tr("Database Update"), tr("CHECK"),
                                    description=tr("This will start the download process and it might take a while to complete."))
    self._update_db_btn.set_click_callback(self._on_update_db)

    self._country_btn = BigButton(tr("Country"), "", description=tr("Select Country"))
    self._country_btn.set_click_callback(lambda: self._select_region("Country"))

    self._state_btn = BigButton(tr("State"), "", description=tr("Select State"))
    self._state_btn.set_click_callback(lambda: self._select_region("State"))

    self._scroller.add_widgets([
      self._mapd_version_btn,
      self._delete_maps_btn,
      self._progress_btn,
      self._update_db_btn,
      self._country_btn,
      self._state_btn,
    ])

  # ------------------------------------------------------------------ helpers
  def _is_china(self) -> bool:
    return self._params.get("OsmLocationName") == CHINA_NATION_REF

  def _downloading(self) -> bool:
    return bool(self._mem_params.get("OSMDownloadLocations") or self._mem_params.get("OSMDownloadBounds"))

  def _update_map_size(self):
    if self._size_thread is not None and self._size_thread.is_alive():
      return
    self._size_thread = threading.Thread(target=self._do_calculate_size, daemon=True).start()

  def _do_calculate_size(self):
    self._map_size = _calculate_map_size()

  def _do_delete_maps(self):
    self._params.put_bool("Mapd_ClearCache", True)
    delete_downloaded_maps(self._params, self._mem_params)
    self._update_map_size()

  def _on_delete_maps(self):
    if self._downloading():
      return
    gui_app.push_widget(BigConfirmationDialog(tr("slide to delete all maps"),
                                              gui_app.texture("icons_mici/setup/red_warning.png", 64, 64),
                                              self._do_delete_maps, red=True))

  def _on_update_db(self):
    if self._downloading():
      return
    gui_app.push_widget(BigConfirmationDialog(tr("Start Download"),
                                              gui_app.texture("icons_mici/settings/device/update.png", 64, 64),
                                              lambda: self._params.put_bool("OsmDbUpdatesCheck", True)))

  # ----------------------------------------------------------- region picking
  def _select_region(self, region_type: str, country: str | None = None):
    if self._downloading():
      return
    country = country or self._params.get("OsmLocationName") or ""
    self._pending_picker = (region_type, country)
    threading.Thread(target=self._fetch_locations_thread, args=(region_type, country), daemon=True).start()

  def _fetch_locations_thread(self, region_type: str, country: str):
    locations = _fetch_locations(region_type, country)

    def apply():
      # only open if the request is still the latest one
      if self._pending_picker == (region_type, country):
        self._pending_picker = None
        self._push_region_picker(region_type, country, locations)

    self._pending_locations = (region_type, country, locations, apply)

  def _push_region_picker(self, region_type: str, country: str, locations: list[tuple[str, str]]):
    is_country = region_type == "Country"
    key = "OsmLocation" if is_country else "OsmState"
    current = self._params.get(f"{key}Name") or ""

    if is_country:
      title = tr("Select Country")
    elif country == CHINA_NATION_REF:
      title = tr("Select Province")
    else:
      title = tr("Select State")

    def on_select(ref: str, name: str):
      self._on_region_selected(region_type, country, key, ref, name)

    gui_app.push_widget(_RegionPickerPage(title, locations, current, on_select))

  def _on_region_selected(self, region_type: str, country: str, key: str, ref: str, name: str):
    if region_type == "Country":
      self._params.put_bool("OsmLocal", True)
      self._params.remove("OsmStateName")
      self._params.remove("OsmStateTitle")

    self._params.put(f"{key}Name", ref)
    self._params.put(f"{key}Title", name)

    if ref in ("US", CHINA_NATION_REF) and region_type == "Country":
      self._select_region("State", country=ref)
    else:
      self._on_update_db()

  # ------------------------------------------------------------------- update
  def show_event(self):
    super().show_event()
    self._update_map_size()
    self._mapd_version_btn.set_value(self._params.get("MapdVersion") or tr("Loading..."))

  def _update_state(self):
    super()._update_state()

    # UI-thread consumption of the background region fetch
    pending = getattr(self, "_pending_locations", None)
    if pending is not None:
      self._pending_locations = None
      pending[3]()

    self._mapd_version_btn.set_value(self._params.get("MapdVersion") or tr("Loading..."))

    downloading = self._downloading()
    pending_check = self._params.get_bool("OsmDbUpdatesCheck")
    busy = downloading or pending_check
    self._progress_btn.set_visible(busy)
    self._delete_maps_btn.set_enabled(not downloading)
    self._update_db_btn.set_enabled(not downloading)
    self._country_btn.set_enabled(not downloading)
    self._state_btn.set_enabled(not downloading)

    location = self._params.get("OsmLocationName")
    self._state_btn.set_visible(location in ("US", CHINA_NATION_REF))
    self._update_db_btn.set_visible(bool(location))

    self._country_btn.set_value(self._params.get("OsmLocationTitle") or "")
    state_label = tr("Province") if self._is_china() else tr("State")
    self._state_btn.set_text(state_label)
    self._state_btn.set_value(self._params.get("OsmStateTitle") or "")

    if busy:
      device._reset_interactive_timeout()
      if downloading and monotonic() - self._last_size_update > MAP_SIZE_REFRESH_INTERVAL:
        self._last_size_update = monotonic()
        self._update_map_size()

      progress = self._params.get("OSMDownloadProgress")
      total = progress.get('total_files', 0) if progress else 0
      done = progress.get('downloaded_files', 0) if progress else 0
      failed = total > 0 and not downloading and done < total

      if failed:
        self._progress_btn.set_text(tr("{}% - Downloading Maps").format(0))
        self._progress_btn.set_value(tr("Error: Invalid download. Retry."))
      elif total > 0 and downloading:
        perc = int(max(0.0, min(100.0, (done / total) * 100.0)))
        self._progress_btn.set_text(tr("{}% - Downloading Maps").format(perc))
        self._progress_btn.set_value(f"{done}/{total} ({perc}%)")
      else:
        self._progress_btn.set_text(tr("{}% - Downloading Maps").format(0))
        self._progress_btn.set_value(tr("Downloading Maps..."))
      self._update_db_btn.set_enabled(False)
    else:
      self._update_db_btn.set_enabled(True)
      ts = self._params.get("OsmDownloadedDate")
      dt: datetime.datetime | None = None
      if ts:
        try:
          ts_f = float(ts)
          if ts_f > 0:
            dt = datetime.datetime.fromtimestamp(ts_f, tz=datetime.UTC)
        except (ValueError, TypeError):
          dt = None
      self._update_db_btn.set_value(tr("Last checked {}").format(time_ago(dt)))

    self._delete_maps_btn.set_value(_fmt_size(self._map_size) if self._map_size else tr("DELETE"))
