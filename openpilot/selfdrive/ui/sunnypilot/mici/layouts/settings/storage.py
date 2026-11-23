"""
Copyright (c) 2026-, mouxan.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import os
import platform
import shutil
import threading

from openpilot.common.hardware.hw import Paths
from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog, BigDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.osm import MAP_PATH, delete_downloaded_maps
from openpilot.selfdrive.ui.sunnypilot.storage_info import (
  directory_size, disk_usage, format_size, model_file_names, model_root_size,
)
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller

try:
  # The webui submodule is the truth source for both the snapshot numbers and
  # the cleanup actions (same as Big GUI storage.py).
  from webui.server.bridge.storage_api import clear_storage, snapshot_storage
  HAS_WEBUI_BACKEND = True
except Exception:
  HAS_WEBUI_BACKEND = False

_DISK_PROBE_PATH = str(Paths.log_root())
CATEGORY_ORDER = ("routes", "models", "maps", "software", "logs", "ota_staging", "scons_cache", "other")

KB = 1024
MB = 1024 ** 2
GB = 1024 ** 3


def _fmt_bytes(num_bytes) -> str:
  """webui formatStorageBytes: 1 decimal GB/MB, rounded KB, raw bytes."""
  n = num_bytes or 0
  if not isinstance(n, (int, float)) or n < 0:
    return "-"
  if n >= GB:
    return f"{n / GB:.1f} GB"
  if n >= MB:
    return f"{n / MB:.1f} MB"
  if n >= KB:
    return f"{round(n / KB)} KB"
  return f"{n} B"


def _category_label(category: str) -> str:
  labels = {
    "routes": tr("Routes"),
    "models": tr("Models"),
    "maps": tr("Maps"),
    "software": tr("Software"),
    "logs": tr("Logs"),
    "ota_staging": tr("OTA staging"),
    "scons_cache": tr("Build cache"),
    "other": tr("Other"),
  }
  return labels[category]


class StorageLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else ui_state.params
    self._data: dict | None = None
    self._busy: set[str] = set()
    self._scanning = False
    self._pending_status: str | None = None
    self._model_clearable: dict[str, int] = {"qcom": 0, "chestnut": 0}

    self._disk_btn = BigButton(tr("Storage Used"), tr("Calculating..."))
    self._disk_btn.set_enabled(False)

    self._refresh_btn = BigButton(tr("Refresh"), tr("SCAN"),
                                  description=tr("Rescan the storage usage now. The scan walks every directory and can take a moment."))
    self._refresh_btn.set_click_callback(lambda: self._refresh(force=True))

    self._category_btns = {cid: self._make_category_btn(cid) for cid in CATEGORY_ORDER}
    self._free_btn = BigButton(tr("Free"), "")
    self._free_btn.set_enabled(False)

    self._warn_btn = GreyBigButton("", "")

    self._cleanup_header = GreyBigButton(tr("Cleanup"), "")
    self._offroad_hint = GreyBigButton("", tr("Cleanup is only available while offroad."))

    self._action_defs = [
      ("routes", tr("Clear route recordings")),
      ("routes_starred", tr("Clear starred routes")),
      ("maps", tr("Clear map cache")),
      ("models_cache", tr("Clear model cache")),
      ("logs", tr("Clear logs")),
      ("scons_cache", tr("Clear build cache")),
      ("download_cache", tr("Clear download cache")),
    ]
    self._action_btns: dict[str, BigButton] = {}
    for category, title in self._action_defs:
      btn = BigButton(title, "")
      btn.set_click_callback(lambda c=category: self._clear_category(c))
      self._action_btns[category] = btn

    self._model_btns: dict[str, BigButton] = {}
    for source, title in (("qcom", tr("Small Model")), ("chestnut", tr("Big Model"))):
      btn = BigButton(title, "")
      btn.set_click_callback(lambda s=source: self._clear_model_source(s))
      self._model_btns[source] = btn

    self._status_btn = BigButton(tr("Last Cleanup"), tr("Nothing cleared yet"))
    self._status_btn.set_enabled(False)

    self._scroller.add_widgets([
      self._disk_btn,
      self._refresh_btn,
      *[self._category_btns[cid] for cid in CATEGORY_ORDER],
      self._free_btn,
      self._warn_btn,
      self._cleanup_header,
      *[self._action_btns[category] for category, _ in self._action_defs],
      self._model_btns["qcom"],
      self._model_btns["chestnut"],
      self._status_btn,
      self._offroad_hint,
    ])

  # ------------------------------------------------------------------ helpers
  def _make_category_btn(self, cid: str) -> BigButton:
    btn = BigButton(_category_label(cid), "")
    btn.set_enabled(False)
    return btn

  @property
  def _offroad(self) -> bool:
    return not ui_state.started

  def _can_clear(self, category: str) -> bool:
    if category in self._busy or not self._offroad:
      return False
    est = (self._data or {}).get("clearable", {}).get(category)
    return bool(est)

  def _can_clear_model(self, source: str) -> bool:
    return self._offroad and f"model:{source}" not in self._busy and bool(self._model_clearable.get(source))

  # -------------------------------------------------------------------- data
  def _refresh(self, force: bool = False):
    if self._scanning:
      return
    self._scanning = True
    self._refresh_btn.set_enabled(False)
    threading.Thread(target=self._load_snapshot, args=(force,), daemon=True).start()

  def _load_snapshot(self, force: bool = False):
    try:
      try:
        data = snapshot_storage(force=force) if HAS_WEBUI_BACKEND else self._legacy_snapshot()
      except Exception:
        data = self._legacy_snapshot() if HAS_WEBUI_BACKEND else None
      if data:
        self._data = data
        self._compute_model_split()
    finally:
      self._scanning = False

  def _legacy_snapshot(self) -> dict:
    """Fallback without the webui package: the subset this page can compute."""
    usage = disk_usage(_DISK_PROBE_PATH)
    models = model_root_size(Paths.model_root())
    maps = directory_size(str(MAP_PATH))
    total = usage.total if usage else 0
    used = usage.used if usage else 0
    free = usage.free if usage else 0
    cats = {"routes": 0, "models": models, "maps": maps, "software": 0, "logs": 0,
            "ota_staging": 0, "scons_cache": 0, "other": max(0, used - models - maps)}
    return {
      "total_bytes": total, "used_bytes": used, "free_bytes": free,
      "free_percent": round(100.0 * free / total, 1) if total else 0,
      "low_space": (free / total < 0.10) if total else False,
      "critical_space": (free / total < 0.02) if total else False,
      "categories": [{"id": cid, "bytes": cats[cid], "percent": round(100.0 * cats[cid] / total, 1) if total else 0}
                     for cid in CATEGORY_ORDER],
      "starred_routes": {"count": 0, "bytes": 0},
      "clearable": {"routes": 0, "routes_starred": 0, "maps": maps, "models_cache": models,
                    "logs": 0, "scons_cache": 0, "download_cache": 0},
    }

  def _compute_model_split(self):
    """Per-source (small=qcom, big=chestnut) clearable bytes, like Big GUI."""
    model_root = str(Paths.model_root())
    try:
      from openpilot.sunnypilot.models.fetcher import get_cached_bundles

      bundles = {source: get_cached_bundles(ui_state.params, source) for source in ("qcom", "chestnut")}
      self._model_clearable = {source: self._model_clearable_bytes(model_root, source, bundles) for source in bundles}
    except Exception:
      self._model_clearable = {"qcom": 0, "chestnut": 0}

  def _model_clearable_bytes(self, model_root: str, source: str, bundles: dict[str, list]) -> int:
    """Bytes a per-source clear would actually free for `source`: files only the
    source's catalog lists and neither selected bundle needs (Big GUI logic)."""
    try:
      from openpilot.sunnypilot.models.helpers import get_selected_bundle

      protected: set[str] = set()
      for s in bundles:
        if selected := get_selected_bundle(ui_state.params, s):
          for model in getattr(selected, "models", []) or []:
            for artifact in (getattr(model, "artifact", None), getattr(model, "metadata", None)):
              name = getattr(artifact, "fileName", "") or ""
              if name:
                protected.add(name)

      other = next(s for s in bundles if s != source)
      other_files: set[str] = set()
      for bundle in bundles.get(other, []) or []:
        other_files |= model_file_names(bundle)

      total = 0
      for bundle in bundles.get(source, []) or []:
        for name in model_file_names(bundle):
          if name in protected or name in other_files:
            continue
          fp = os.path.join(model_root, name)
          if os.path.isfile(fp):
            total += os.path.getsize(fp)
          else:
            directory = os.path.dirname(fp) or model_root
            total += sum(os.path.getsize(os.path.join(directory, f))
                         for f in os.listdir(directory) if f.startswith(name + ".chunk"))
      return total
    except Exception:
      return 0

  # ----------------------------------------------------------------- actions
  def _set_status(self, text: str):
    # applied on the UI thread from _update_state
    self._pending_status = text

  def _confirm_and_clear(self, category: str, message: str):
    def on_confirm():
      self._busy.add(category)

      def worker():
        try:
          if HAS_WEBUI_BACKEND:
            res = clear_storage(category)
          else:
            res = self._legacy_clear(category)
          freed = res.get("freed_bytes", 0) if res.get("ok") else 0
          if res.get("ok"):
            self._set_status(tr("Freed {size}").format(size=_fmt_bytes(freed)))
          else:
            self._set_status(res.get("error", tr("Nothing to clear")))
        except Exception as exc:
          self._set_status(str(exc))
        finally:
          self._busy.discard(category)
          self._refresh()

      threading.Thread(target=worker, daemon=True).start()

    gui_app.push_widget(BigConfirmationDialog(message,
                                              gui_app.texture("icons_mici/setup/red_warning.png", 64, 64),
                                              on_confirm, red=True))

  def _clear_category(self, category: str):
    if not self._can_clear(category):
      if not self._offroad:
        gui_app.push_widget(BigDialog(tr("Cleanup is only available while offroad."), ""))
      return
    est = (self._data or {}).get("clearable", {}).get(category) or 0
    size_text = _fmt_bytes(est)
    if category == "routes_starred":
      count = (self._data or {}).get("starred_routes", {}).get("count", 0)
      message = tr("This will permanently delete {count} starred routes ({size}). Continue?").format(
        count=count, size=size_text or _fmt_bytes((self._data or {}).get("starred_routes", {}).get("bytes", 0)))
    elif category == "scons_cache":
      message = tr("Clearing the build cache frees space, but the next compile will take significantly longer. Continue?")
    elif category == "routes":
      message = tr("Deletes non-preserved driving segments. Starred and recent routes are kept.")
    else:
      message = tr("This will free about {size}. Continue?").format(size=size_text)
    self._confirm_and_clear(category, message)

  def _legacy_clear(self, category: str) -> dict:
    """Fallback without the webui package: the two old actions only."""
    freed = 0
    if category == "models_cache":
      self._mem_params.put_bool("ModelManager_ClearCache", True)
      model_root = str(Paths.model_root())
      active = (ui_state.params.get("ActiveModel") or "").strip()
      for name in os.listdir(model_root):
        if name == active:
          continue
        fp = os.path.join(model_root, name)
        freed += directory_size(fp)
        shutil.rmtree(fp, ignore_errors=True)
    elif category == "maps":
      delete_downloaded_maps(self._params, self._mem_params)
      freed = directory_size(str(MAP_PATH))
    return {"ok": True, "category": category, "freed_bytes": freed}

  def _clear_model_source(self, source: str):
    if not self._can_clear_model(source):
      return
    size_text = format_size(self._model_clearable.get(source, 0))
    message = (tr("This will delete downloaded small-model files except the one in use (about {size}). Continue?")
               if source == "qcom" else
               tr("This will delete downloaded big-model files except the one in use (about {size}). Continue?")).format(size=size_text)

    def on_confirm():
      self._busy.add(f"model:{source}")

      def worker():
        try:
          freed = self._clear_model_files(source)
          self._set_status(tr("Freed {size}").format(size=_fmt_bytes(freed)))
        except Exception as exc:
          self._set_status(str(exc))
        finally:
          self._busy.discard(f"model:{source}")
          self._compute_model_split()
          self._refresh()

      threading.Thread(target=worker, daemon=True).start()

    gui_app.push_widget(BigConfirmationDialog(message,
                                              gui_app.texture("icons_mici/setup/red_warning.png", 64, 64),
                                              on_confirm, red=True))

  def _clear_model_files(self, source: str) -> int:
    """Delete the per-source candidates, together with their chunk files."""
    model_root = str(Paths.model_root())
    from openpilot.sunnypilot.models.fetcher import get_cached_bundles
    from openpilot.sunnypilot.models.helpers import get_selected_bundle

    bundles = {s: get_cached_bundles(ui_state.params, s) for s in ("qcom", "chestnut")}
    protected: set[str] = set()
    for s in bundles:
      if selected := get_selected_bundle(ui_state.params, s):
        for model in getattr(selected, "models", []) or []:
          for artifact in (getattr(model, "artifact", None), getattr(model, "metadata", None)):
            name = getattr(artifact, "fileName", "") or ""
            if name:
              protected.add(name)

    other = next(s for s in bundles if s != source)
    other_files: set[str] = set()
    for bundle in bundles.get(other, []) or []:
      other_files |= model_file_names(bundle)

    freed = 0
    for bundle in bundles.get(source, []) or []:
      for name in model_file_names(bundle):
        if name in protected or name in other_files:
          continue
        base = os.path.join(model_root, name)
        directory = os.path.dirname(base) or model_root
        for filename in ([name] if os.path.isfile(base) else []) + \
                        [f for f in os.listdir(directory) if f.startswith(name + ".chunk")]:
          fp = os.path.join(directory, filename)
          try:
            freed += os.path.getsize(fp)
            os.remove(fp)
          except OSError:
            pass
    return freed

  # ------------------------------------------------------------------ update
  def show_event(self):
    super().show_event()
    self._refresh()

  def _update_state(self):
    super()._update_state()

    if self._pending_status is not None:
      self._status_btn.set_value(self._pending_status)
      self._pending_status = None

    data = self._data
    if data is None:
      return

    total = data.get("total_bytes", 0)
    self._disk_btn.set_value(
      f"{_fmt_bytes(data.get('used_bytes'))} / {_fmt_bytes(total)}  ·  {tr('{} free').format(_fmt_bytes(data.get('free_bytes')))}")

    for cat in data.get("categories", []):
      cid = cat.get("id")
      if cid in self._category_btns:
        self._category_btns[cid].set_value(f"{_fmt_bytes(cat.get('bytes', 0))} · {cat.get('percent', 0)}%")
    self._free_btn.set_value(f"{_fmt_bytes(data.get('free_bytes', 0))} · {data.get('free_percent', 0)}%")

    if data.get("critical_space"):
      self._warn_btn.set_text(tr("Free up storage (less than 2% space remaining)"))
      self._warn_btn.set_visible(True)
    elif data.get("low_space"):
      self._warn_btn.set_text(tr("Storage is running low (less than 10% free)."))
      self._warn_btn.set_visible(True)
    else:
      self._warn_btn.set_visible(False)

    for category, btn in self._action_btns.items():
      est = data.get("clearable", {}).get(category)
      btn.set_value(tr("About {size} can be freed").format(size=_fmt_bytes(est)) if est else tr("Nothing to clear"))
      btn.set_enabled(self._can_clear(category))

    for source, btn in self._model_btns.items():
      est = self._model_clearable.get(source, 0)
      btn.set_value(tr("About {size} can be freed").format(size=format_size(est)) if est else tr("Nothing to clear"))
      btn.set_enabled(self._can_clear_model(source))

    self._offroad_hint.set_visible(not self._offroad)
    self._refresh_btn.set_enabled(not self._scanning)
