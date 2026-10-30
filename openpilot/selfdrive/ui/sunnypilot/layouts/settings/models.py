"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import os
import re
import time
import pyray as rl

from openpilot.cereal import custom
from openpilot.sunnypilot.models.default_model import DEFAULT_MODEL
from openpilot.sunnypilot.models.helpers import ACTIVE_BUNDLE_KEYS, get_selected_bundle, resolve_bundle_by_ref
from openpilot.common.constants import CV
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.selfdrive.ui.sunnypilot.accelerator_link import LINK_MODES, LINK_MODE_TITLES, big_model_note, link_mode, link_status, \
  link_toggle_meaningful, standin_model
from openpilot.selfdrive.ui.sunnypilot.model_info import (active_source, big_model_state, bundles_for_source, carrying_model, default_model_name,
                                                           local_model_note, model_cache_size_mb, queued_name,
                                                           refresh_in_progress, refresh_model_list)
from openpilot.sunnypilot.jetlink_adapter import KEYS, MODES
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog, ConfirmDialog
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.toggle import ON_COLOR

from openpilot.sunnypilot.models.runners.constants import CUSTOM_MODEL_PATH
from openpilot.system.ui.sunnypilot.lib.styles import style
from openpilot.system.ui.sunnypilot.lib.utils import NoElideButtonAction, ScrollingButtonAction
from openpilot.system.ui.sunnypilot.widgets.list_view import ListItemSP, toggle_item_sp, option_item_sp, multiple_button_item_sp
from openpilot.system.ui.sunnypilot.widgets.download_status import download_status_item
from openpilot.system.ui.sunnypilot.widgets.tree_dialog import TreeOptionDialog, TreeNode, TreeFolder
from openpilot.system.ui.sunnypilot.widgets.progress_bar import progress_item

if gui_app.sunnypilot_ui():
  from openpilot.system.ui.sunnypilot.widgets.list_view import button_item_sp as button_item


class ModelsLayout(Widget):
  def __init__(self):
    super().__init__()
    self.model_manager = None
    self.download_status = None
    self.prev_download_status = None
    self.model_dialog = None
    self._selection_source = None
    self._downloading = False
    self._verifying = False
    self._clearing = False
    self._refreshing = False
    self._refresh_start: float | None = None
    self._last_note = None
    self.last_cache_calc_time = 0
    self._link_status: str | None = None

    self._initialize_items()

    self.clear_cache_item.action_item.set_value(f"{self.calculate_cache_size():.2f} MB")
    for ctrl, key in [(self.lane_turn_value_control, "LaneTurnValue"), (self.delay_control, "LagdToggleDelay"), (self.camera_offset, "CameraOffset")]:
      ctrl.action_item.set_value(int(float(ui_state.params.get(key, return_default=True)) * 100))

    self._scroller = Scroller(self.items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self.current_model_item = ListItemSP(
      title=tr("Current Model"),
      description="",
      action_item=NoElideButtonAction(tr("SELECT")),
      callback=self._handle_current_model_clicked
    )

    # 2026-10-17: 上游把模型选择拆成 small(qcom) / big(chestnut) 两个槽位，各选各的
    # catalog（没装 chestnut 时 big 槽位由 jetlink 的加速器跑）。本树此前只剩
    # current_model_item（走 active_source()），没有 chestnut 时选择器里就只有小模型列表，
    # 与上游不一致。这里补回两个槽位行；current_model_item 继续作状态展示。
    self.small_model_item = ListItemSP(
      title=tr("Small Model"),
      description="",
      action_item=ScrollingButtonAction(tr("SELECT")),
      callback=lambda: self._open_source_dialog("qcom"),
    )

    self.big_model_item = ListItemSP(
      title=tr("Big Model"),
      description="",
      action_item=ScrollingButtonAction(tr("SELECT")),
      callback=lambda: self._open_source_dialog("chestnut"),
    )

    # round-23 重排（7399ffe498）把这两个构造块整段丢了，但 _initialize_items 末尾的
    # self.items 列表仍在引用它们 → ModelsLayout() 构造即 AttributeError，
    # ui 在 SettingsLayout 里建面板时抛异常退出(1)，manager 每 6 秒重启一次 ui，
    # 屏幕就停死在启动画面。语义按 2e36dcdd71 原文恢复，不做任何行为改动。
    self.accelerator_link_item = multiple_button_item_sp(
      tr("Jetlink"),
      self._link_description(""),
      buttons=[lambda m=m: tr(LINK_MODE_TITLES[m]) for m in MODES],
      param=KEYS.link, button_width=300, inline=False)

    self.download_item = download_status_item(lambda: tr("Download") if self._downloading else tr("Model Status"))

    self.supercombo_label = progress_item(tr("Driving Model"))
    self.vision_label = progress_item(tr("Vision Model"))
    self.policy_label = progress_item(tr("Policy Model"))
    self.off_policy_label = progress_item(tr("Off-Policy Model"))
    self.on_policy_label = progress_item(tr("On-Policy Model"))

    # the label is read every frame so a queued refresh shows as FETCHING... until both
    # catalogs are stamped (refresh_in_progress), which is also what gates the button
    self.refresh_item = button_item(tr("Refresh Model List"),
                                    lambda: tr("FETCHING...") if self._refreshing else tr("REFRESH"), "",
                                    self._refresh_models)

    self.clear_cache_item = ListItemSP(
      title=tr("Clear Model Cache"),
      description="",
      action_item=NoElideButtonAction(tr("CLEAR")),
      callback=self._clear_cache
    )

    self.cancel_download_item = button_item(tr("Cancel Download"), tr("Cancel"), "", lambda: ui_state.params.remove("ModelManager_DownloadRef"))

    self.lane_turn_value_control = option_item_sp(tr("Adjust Lane Turn Speed"), "LaneTurnValue", 500, 2000,
                                                  tr("Set the maximum speed for lane turn desires. Default is 19 mph."),
                                                  int(round(100 / CV.MPH_TO_KPH)), None, True, "", style.BUTTON_ACTION_WIDTH, None, True,
                                                  lambda v: f"{int(round(v / 100 * (CV.MPH_TO_KPH if ui_state.is_metric else 1)))}" +
                                                            f" {tr('km/h') if ui_state.is_metric else tr('mph')}")

    self.lane_turn_desire_toggle = toggle_item_sp(tr("Use Lane Turn Desires"),
                                                  tr("If you're driving at 20 mph (32 km/h) or below and have your blinker on, " +
                                                     "the car will plan a turn in that direction at the nearest drivable path. " +
                                                     "This prevents situations (like at red lights) where the car might plan the wrong turn direction."),
                                                  param="LaneTurnDesire")

    self.delay_control = option_item_sp(tr("Adjust Software Delay"), "LagdToggleDelay", 5, 50,
                                        tr("Adjust the software delay when Live Learning Steer Delay is toggled off. The default software delay value is 0.2"),
                                        1, None, True, "", style.BUTTON_ACTION_WIDTH, None, True, lambda v: f"{v / 100:.2f}s")

    self.lagd_toggle = toggle_item_sp(tr("Live Learning Steer Delay"), "", param="LagdToggle")

    self._blendful_desc = tr("Adds a gentle nudge toward lane center on top of the model's own steering, stronger when lane lines are clear." +
                             " Yields around obstacles. Not available with the Default model.")
    self.blendful_toggle = toggle_item_sp(tr("Lane Center Assist (Alpha)"), self._blendful_desc, param="Blendful")

    self.camera_offset = option_item_sp(tr("Adjust Camera Offset"), "CameraOffset", -35, 35,
                                        tr("Virtually shift camera's perspective to move model's center to Left(+ values) or Right (- values)"),
                                        1, None, True, "", style.BUTTON_ACTION_WIDTH, None, True,
                                        lambda v: f"{v / 100:.2f} m")

    self.items = [self.small_model_item, self.big_model_item, self.accelerator_link_item, self.cancel_download_item, self.download_item, self.refresh_item,
                  self.clear_cache_item,
                  self.blendful_toggle, self.lane_turn_desire_toggle, self.lane_turn_value_control, self.lagd_toggle, self.delay_control, self.camera_offset]
    self._refresh_accelerator_items()

  @staticmethod
  def _link_description(status: str) -> str:
    what = tr("Run big models over a connected device running Jetlink. Turns off ADB.")
    return f"{what} {status}".strip()

  def _refresh_accelerator_items(self):
    # the setting is a param read, so this rides the half-second tick
    self.accelerator_link_item.set_visible(link_toggle_meaningful())
    self.accelerator_link_item.action_item.set_selected_button(LINK_MODES.index(link_mode()))
    self.accelerator_link_item.action_item.set_enabled(ui_state.is_offroad())
    status = link_status()
    if status != self._link_status:
      self._link_status = status
      self.accelerator_link_item.set_description(self._link_description(status))

  def _update_lagd_description(self, lagd_toggle: bool):
    desc = tr("Enable this for the car to learn and adapt its steering response time. Disable to use a fixed steering response time. "
              "Keeping this on provides the stock openpilot experience.")
    if lagd_toggle:
      desc += f"<br>{tr('Live Steer Delay:')} {ui_state.sm['lateralDelay'].lateralDelay:.3f} s"
    elif ui_state.CP is not None:
      sw = float(ui_state.params.get("LagdToggleDelay", "0.2"))
      cp = ui_state.CP.steerActuatorDelay
      desc += f"<br>{tr('Actuator Delay:')} {cp:.2f} s + {tr('Software Delay:')} {sw:.2f} s = {tr('Total Delay:')} {cp + sw:.2f} s"
    self.lagd_toggle.set_description(desc)

  def _is_downloading(self):
    return (self.model_manager and self.model_manager.selectedBundle and
            self.model_manager.selectedBundle.status == custom.ModelManagerSP.DownloadStatus.downloading)

  @staticmethod
  def calculate_cache_size():
    cache_size = 0.0
    if os.path.exists(CUSTOM_MODEL_PATH):
      cache_size = sum(os.path.getsize(os.path.join(CUSTOM_MODEL_PATH, file)) for file in os.listdir(CUSTOM_MODEL_PATH)) / (1024**2)
    return cache_size

  def _clear_cache(self):
    def _callback(response):
      if response == DialogResult.CONFIRM:
        ui_state.params.put_bool("ModelManager_ClearCache", True)
        self.clear_cache_item.action_item.set_value(f"{self.calculate_cache_size():.2f} {tr('MB')}")

    dialog = ConfirmDialog(tr("This will delete ALL downloaded models from the cache except the currently active model. Are you sure?"),
                           tr("Clear Cache"), callback=_callback)
    gui_app.push_widget(dialog)

  def _refresh_models(self):
    refresh_model_list()
    self._refresh_start = time.monotonic()

  # ---- download mirror ------------------------------------------------- #
  # removed: mirror/catalog source selection is automatic now. The sources
  # (hf-mirror vs direct, raw vs jsDelivr vs proxies) are latency-probed at
  # download/fetch time (sunnypilot/models/http_probe.py); the params remain
  # as an off-UI override for private mirrors.


  def _slot_segments(self):
    """small and big slots side by side; green marks the slot whose pick is actually
    driving (runner-matched, so a failed Default big greens neither slot), an empty
    slot shows its default."""
    big_state = big_model_state()
    carry_source, carry_internal, _ = carrying_model()
    segments = []
    for source, label in (("qcom", tr("small")), ("chestnut", tr("big"))):
      if segments:
        segments.append(("|", rl.GRAY, None, None))
      bundle = get_selected_bundle(ui_state.params, source)
      name = bundle.internalName if bundle else default_model_name(source)
      color = ON_COLOR if (source == carry_source and name == carry_internal) else rl.LIGHTGRAY
      name = "● " + name
      if source == "chestnut":
        if big_state == 'failed':
          color = rl.RED
        elif big_state == 'loading':
          color = rl.GOLD
      segments.append((label, rl.GRAY, None, None))
      segments.append((name, color, None, None))
    return segments

  def _handle_bundle_download_progress(self):
    # every Model.Type the schema can carry needs a row: deep models ship one
    # `chunked` artifact for the whole bundle (upstream "Support Deep Models"),
    # and every bundle the catalog serves today is chunked. Without the chunked
    # entry no row matched, so a download showed neither a percentage bar nor a
    # status text at all.
    labels = {custom.ModelManagerSP.Model.Type.supercombo: self.supercombo_label,
              custom.ModelManagerSP.Model.Type.vision: self.vision_label,
              custom.ModelManagerSP.Model.Type.policy: self.policy_label,
              custom.ModelManagerSP.Model.Type.offPolicy: self.off_policy_label,
              custom.ModelManagerSP.Model.Type.onPolicy: self.on_policy_label,
              custom.ModelManagerSP.Model.Type.navigation: self.supercombo_label,
              custom.ModelManagerSP.Model.Type.chunked: self.supercombo_label}
    for label in labels.values():
      label.set_visible(False)
    self.cancel_download_item.set_visible(False)

    if not self.model_manager or (not self.model_manager.selectedBundle and not self.model_manager.activeBundle):
      return

    bundle = self.model_manager.selectedBundle if self._is_downloading() or (
      self.model_manager.selectedBundle and self.model_manager.selectedBundle.status == custom.ModelManagerSP.DownloadStatus.failed
    ) else self.model_manager.activeBundle
    if not bundle:
      return

    self.download_status = bundle.status
    status_changed = self.prev_download_status != self.download_status
    self.prev_download_status = self.download_status

    self.cancel_download_item.set_visible(ui_state.params.get("ModelManager_DownloadRef") is not None)

    if (current_time := time.monotonic()) - self.last_cache_calc_time > 0.5:
      self.last_cache_calc_time = current_time
      self.clear_cache_item.action_item.set_value(f"{self.calculate_cache_size():.2f} {tr('MB')}")

    if self.download_status == custom.ModelManagerSP.DownloadStatus.downloading:
      device._reset_interactive_timeout()

    for model in bundle.models:
      # an unknown type (a future Model.Type) still gets the driving-model row:
      # dropping the row is how the chunked catalogs lost their download status
      label = labels.get(getattr(model.type, 'raw', model.type), self.supercombo_label)
      label.set_visible(True)
      p = model.artifact.downloadProgress
      text, show, color = tr("pending - {}").format(bundle.displayName), False, rl.GRAY
      if p.status == custom.ModelManagerSP.DownloadStatus.downloading:
        text, show = f"{int(p.progress)}% - {bundle.displayName}", True
      elif p.status in (custom.ModelManagerSP.DownloadStatus.downloaded, custom.ModelManagerSP.DownloadStatus.cached):
        status_text = tr("from cache" if p.status == custom.ModelManagerSP.DownloadStatus.cached else "downloaded")
        text, color = f"{bundle.displayName} - {status_text if status_changed else tr('ready')}", ON_COLOR
      elif p.status == custom.ModelManagerSP.DownloadStatus.failed:
        text, color = tr("download failed - {}").format(bundle.displayName), rl.RED
      label.action_item.update(p.progress, text, show, color)

    # the cache/refresh row gates on these, and the chunked rewrite dropped the only writer
    ds = custom.ModelManagerSP.DownloadStatus
    self._downloading = any(getattr(m.artifact.downloadProgress.status, 'raw', m.artifact.downloadProgress.status) == ds.downloading
                            for m in bundle.models)
    self._verifying = any(getattr(m.artifact.downloadProgress.status, 'raw', m.artifact.downloadProgress.status) == ds.verifying
                          for m in bundle.models)

  @staticmethod
  def _show_reset_params_dialog():
    def _callback(response):
      if response == DialogResult.CONFIRM:
        ui_state.params.remove("CalibrationParams")
        ui_state.params.remove("LiveTorqueParameters")
    msg = tr("Model download has started in the background. We suggest resetting calibration. Would you like to do that now?")
    dialog = ConfirmDialog(msg, tr("Reset Calibration"), callback=_callback)
    gui_app.push_widget(dialog)
  def _set_item_note(item, text):
    # a description renders only while shown; hide before clearing or the
    # empty description keeps its visible state
    if text:
      item.set_description(text)
      item.show_description(True)
    else:
      item.show_description(False)
      item.set_description("")

  def _status_note(self) -> str:
    """The failover story for the Model Status row. A chestnut's is one-way big ->
    small and runner-matched: a Default big can only fall back to the Default
    small (stock modeld), a custom big has no automatic fallback yet.
    Jetlink's goes both ways, all drive."""
    view = ui_state.jetlink_view
    accelerator = view is not None
    if not (ui_state.chestnut_present or accelerator):
      return ""
    fallback_name = default_model_name("qcom")
    state = big_model_state()
    if accelerator:
      # named by jetlink: the slot's pick, or its default, which can be
      # newer than the chestnut's. The small model the user picked drives in
      # its place, so it reads like a Default big
      big_name = view.model or tr("The big model")
      big_is_default = True
      if small := get_selected_bundle(ui_state.params, "qcom"):
        fallback_name = small.internalName
    else:
      big_bundle = get_selected_bundle(ui_state.params, "chestnut")
      big_name = big_bundle.internalName if big_bundle else default_model_name("chestnut")
      big_is_default = big_bundle is None
    if state == 'failed':
      if big_is_default:
        return tr("Big model unavailable, {} is driving until the next drive.").format(fallback_name)
      return tr("Big model unavailable until the next drive.")
    if state == 'loading':
      if big_is_default:
        return tr("{} drives until the big model is ready.").format(fallback_name)
      return tr("Getting the big model ready.")
    if state == 'ready':
      # the swap window, not the model, is what is missing now: it opens when
      # nothing is in control
      return tr("{} is ready. Disengage fully, then re-engage to switch.").format(big_name)
    if accelerator and not view.ready:
      if standin := standin_model():
        # the last model the Jetson built drives until the pick is downloaded and built
        return tr("{} drives until {} is ready.").format(standin, big_name)
      return tr("{} will drive when Jetlink is ready.").format(big_name)
    if accelerator:
      # it rejoins all drive and a drop is announced as it happens, so there is
      # no "until the next drive" to warn of
      return tr("{} will drive.").format(big_name)
    if big_is_default:
      return tr("{} will drive. If it fails during a drive, {} takes over until the next drive.").format(big_name, fallback_name)
    return tr("{} will drive when the chestnut is ready.").format(big_name)

  @staticmethod
  def _download_row_state(progresses, name: str) -> dict:
    """Maps a bundle's artifact progress to DownloadStatusAction.update kwargs."""
    # .raw: _DynamicEnum equals its int but does not hash like it
    statuses = {getattr(p.status, 'raw', p.status) for p in progresses}
    progress = sum(p.progress for p in progresses) / len(progresses)
    ds = custom.ModelManagerSP.DownloadStatus

    if any(p.canceling for p in progresses):
      return {"name": name, "downloading": True, "progress": progress, "status_text": tr("canceling...")}
    if ds.failed in statuses:
      # close.png is authored black and a tint cannot lift it, hence close2
      return {"name": name, "status_text": tr("download failed"), "text_color": rl.RED, "icon": "icons/close2.png"}
    if ds.verifying in statuses:
      return {"name": name, "downloading": True, "progress": progress, "status_text": tr("verifying")}
    if ds.downloading in statuses:
      speed = max((p.speed for p in progresses), default=0.0)
      status_text = f"{speed / 1024 ** 2:.1f} MB/s" if speed > 0 else "--.- MB/s"
      return {"name": name, "downloading": True, "progress": progress, "status_text": status_text}
    if statuses <= {ds.downloaded, ds.cached}:
      return {"name": name, "text_color": ON_COLOR, "icon": "icons/checkmark.png"}
    # circled_slash is authored grey; tinting it again only darkens it
    return {"name": name, "text_color": rl.GRAY, "icon": "icons/circled_slash.png", "icon_color": rl.WHITE}

  def _on_model_selected(self, result):
    if result != DialogResult.CONFIRM:
      return
    selected_ref = self.model_dialog.selection_ref
    source = self._selection_source or active_source()
    if selected_ref == "Default":
      if source in ACTIVE_BUNDLE_KEYS:
        ui_state.params.remove(ACTIVE_BUNDLE_KEYS[source])
      self._show_reset_params_dialog()
    elif selected_bundle := self._resolve_selected_bundle(selected_ref):
      ui_state.params.put("ModelManager_DownloadRef", selected_bundle.ref)
      if self.model_manager.activeBundle and selected_bundle.generation != self.model_manager.activeBundle.generation:
        self._show_reset_params_dialog()
    self.model_dialog = None

  @staticmethod
  def _resolve_selected_bundle(ref):
    """The bundle behind `ref`, whichever slot's catalog lists it: a big pick lives in the
    chestnut catalog, which availableBundles (the active source's) does not carry."""
    source_bundles = {source: bundles_for_source(source) for source in ("qcom", "chestnut")}
    resolved = resolve_bundle_by_ref(ref, source_bundles)
    return resolved[0] if resolved else None

  @staticmethod
  def _bundle_to_node(bundle, noted: bool = False):
    # a big model's line says whether the Jetson has built it or the comma has it;
    # every other line says what the disk holds, so an interrupted fetch is visible
    note = big_model_note(bundle.ref) if noted else local_model_note(bundle)
    name = f"{bundle.displayName} · {note}" if note else bundle.displayName
    return TreeNode(bundle.ref, {'display_name': name, 'short_name': bundle.internalName})

  def _get_folders(self, favorites, bundles=None, noted: bool = False):
    # 上游新签名带 bundles/noted；本 fork 的 _handle_current_model_clicked 仍按 1 参调用，故补默认值
    bundles = self.model_manager.availableBundles if bundles is None else bundles
    folders = {}
    for bundle in bundles:
      folders.setdefault(next((ov_ride.value for ov_ride in bundle.overrides if ov_ride.key == "folder"), ""), []).append(bundle)

    folders_list = [TreeFolder("", [TreeNode("Default", {'display_name': tr("{} (Default)").format(DEFAULT_MODEL), 'short_name': "Default"})])]
    for folder, folder_bundles in sorted(folders.items(), key=lambda x: max((bundle.index for bundle in x[1]), default=-1), reverse=True):
      folder_bundles.sort(key=lambda bundle: bundle.index, reverse=True)
      name = folder + (f" - (Updated: {m.group(1)})" if folder_bundles and (m := re.search(r'\(([^)]*)\)[^(]*$', folder_bundles[0].displayName)) else "")
      folders_list.append(TreeFolder(name, [self._bundle_to_node(bundle, noted) for bundle in folder_bundles]))

    if favorites and (fav_bundles := [bundle for bundle in bundles if bundle.ref in favorites]):
      folders_list.insert(0, TreeFolder(tr("Favorites"), [self._bundle_to_node(bundle, noted) for bundle in fav_bundles]))
    return folders_list

  def _handle_current_model_clicked(self):
    self._selection_source = active_source()
    favs = ui_state.params.get("ModelManager_Favs")
    favorites = set(favs.split(';')) if favs else set()
    folders_list = self._get_folders(favorites)

    active_ref = self.model_manager.activeBundle.ref if self.model_manager.activeBundle else "Default"
    self.model_dialog = TreeOptionDialog(tr("Select a Model"), folders_list, active_ref, "ModelManager_Favs",
                                         get_folders_fn=self._get_folders, on_exit=self._on_model_selected)
    gui_app.push_widget(self.model_dialog)

  def _open_source_dialog(self, source):
    """Pick a bundle for one slot: "qcom" (small) or "chestnut" (big).

    Upstream lets both slots be chosen independently, so the picker lists that slot's
    catalog even when the other slot is the one currently driving.
    """
    self._selection_source = source
    favs = ui_state.params.get("ModelManager_Favs")
    favorites = set(favs.split(';')) if favs else set()
    folders_list = self._source_folders(favorites, source)
    if not folders_list:
      gui_app.push_widget(alert_dialog(tr("No models are available for this hardware yet. Connect to the internet and refresh the model list.")))
      return
    self.model_dialog = TreeOptionDialog(tr("Select a Model"), folders_list, self._slot_active_ref(source), "ModelManager_Favs",
                                         get_folders_fn=lambda favs: self._source_folders(favs, source), on_exit=self._on_model_selected)
    gui_app.push_widget(self.model_dialog)

  def _source_folders(self, favorites, source):
    bundles = bundles_for_source(source)
    if not bundles:
      return []
    folders_list = [TreeFolder("", [TreeNode("Default", {'display_name': default_model_name(source)})])]
    folders_list.extend(self._get_folders(favorites, bundles, noted=source == "chestnut"))
    return folders_list

  @staticmethod
  def _slot_active_ref(source: str) -> str:
    bundle = get_selected_bundle(ui_state.params, source)
    return bundle.ref if bundle else "Default"

  def _update_state(self):
    advanced_controls: bool = ui_state.params.get_bool("ShowAdvancedControls")
    turn_desire: bool = ui_state.params.get_bool("LaneTurnDesire")
    live_delay: bool = ui_state.params.get_bool("LagdToggle")
    camera_offset: bool = ui_state.params.get("ModelManager_ActiveBundle") is not None

    self.lane_turn_desire_toggle.action_item.set_state(turn_desire)
    self.lane_turn_value_control.set_visible(turn_desire and advanced_controls)
    self.lagd_toggle.action_item.set_state(live_delay)

    blendful_allowed = ui_state.active_runner_tinygrad
    if blendful_allowed:
      self.blendful_toggle.action_item.set_state(ui_state.params.get_bool("Blendful"))
      self.blendful_toggle.action_item.set_enabled(True)
    else:
      self.blendful_toggle.action_item.set_state(False)
      self.blendful_toggle.action_item.set_enabled(False)

    blendful_desc = self._blendful_desc if blendful_allowed else \
      f"<b>{tr('Select a non-Default model to use Lane Center Assist.')}</b><br><br>{self._blendful_desc}"
    if self.blendful_toggle.description != blendful_desc:
      self.blendful_toggle.set_description(blendful_desc)
      self.blendful_toggle.show_description(not blendful_allowed)

    self.delay_control.set_visible(not live_delay and advanced_controls)
    new_step = int(round(100 / CV.MPH_TO_KPH)) if ui_state.is_metric else 100
    if self.lane_turn_value_control.action_item is not None and self.lane_turn_value_control.action_item.value_change_step != new_step:
      self.lane_turn_value_control.action_item.value_change_step = new_step
    self.camera_offset.set_visible(camera_offset)

    self._update_lagd_description(live_delay)
    self.model_manager = ui_state.sm["modelManagerSP"]
    self._handle_bundle_download_progress()
    active_name = self.model_manager.activeBundle.internalName if self.model_manager and self.model_manager.activeBundle.ref else tr("{} (Default)").format(DEFAULT_MODEL)
    self.current_model_item.action_item.set_value(active_name)

    for item, source in ((self.small_model_item, "qcom"), (self.big_model_item, "chestnut")):
      slot_bundle = get_selected_bundle(ui_state.params, source)
      item.action_item.set_value(slot_bundle.internalName if slot_bundle else default_model_name(source))

    offroad = ui_state.is_offroad()
    self.current_model_item.action_item.set_enabled(offroad)
    self.current_model_item.set_description("" if offroad else tr("Only available when vehicle is off, or always offroad mode is on"))
    for item in (self.small_model_item, self.big_model_item):
      item.action_item.set_enabled(offroad)

    # manager is offroad-only, so a refresh queued onroad would never be serviced
    self._refreshing = refresh_in_progress(self._refresh_start)
    self.refresh_item.action_item.set_enabled(offroad and not self._downloading and not self._refreshing)

    self._refresh_accelerator_items()

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()
