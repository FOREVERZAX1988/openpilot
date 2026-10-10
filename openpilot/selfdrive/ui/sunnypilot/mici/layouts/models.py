"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import pyray as rl

from openpilot.cereal import custom
from openpilot.sunnypilot.models.default_model import DEFAULT_MODEL
from openpilot.sunnypilot.models.helpers import ACTIVE_BUNDLE_KEYS, get_selected_bundle
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiToggle
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.models import ModelsLayout
from openpilot.selfdrive.ui.ui_state import ui_state, device
from openpilot.selfdrive.ui.sunnypilot.accelerator_link import LINK_MODES, LINK_PARAM, link_mode, link_toggle_meaningful
from openpilot.selfdrive.ui.sunnypilot.model_info import (active_source, big_model_progress, big_model_state, bundles_for_source,
                                                           carrying_model, default_model_name, model_cache_size_mb, model_info,
                                                           queued_name, refresh_in_progress, refresh_model_list, standin_model)
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.scroller import NavScroller


# the value line: the mode, and what it is for
LINK_MODE_LABELS = {"off": "off", "usb": "usb: mac, linux, android", "ios": "iOS: iPhone, iPad", "wifi": "wi-fi"}


class AcceleratorLinkToggle(BigMultiToggle):
  """off, usb, ios, wi-fi, a pill each, and the value line says what the mode is for.
  The pills follow the param, not a tap. Locked while onroad and drawn so, like
  the model buttons beside it: jetlink switches the link only parked."""

  def __init__(self):
    super().__init__(tr("jetlink"), [tr(LINK_MODE_LABELS[m]) for m in LINK_MODES])
    self._mode = link_mode()
    self._show()
    self.set_enabled(lambda: ui_state.is_offroad())

  def _show(self) -> None:
    value = self._options[LINK_MODES.index(self._mode)]
    if value != self.get_value():
      self.set_value(value)

  def _handle_mouse_release(self, mouse_pos) -> None:
    BigButton._handle_mouse_release(self, mouse_pos)
    if self.enabled:
      self._mode = LINK_MODES[(LINK_MODES.index(self._mode) + 1) % len(LINK_MODES)]
      ui_state.params.put(LINK_PARAM, LINK_MODES.index(self._mode), block=True)
    self._show()

  def _draw_content(self, btn_y: float) -> None:
    BigButton._draw_content(self, btn_y)
    x = self._rect.x + self._rect.width - self._txt_enabled_toggle.width
    for i in range(len(LINK_MODES)):
      self._draw_pill(x, btn_y + 35 * i, LINK_MODES[i] == self._mode)

  def refresh(self) -> None:
    self._mode = link_mode()
    self._show()


def _model_info() -> tuple[str, str, str]:
  """(active model, info header, info text) for the panel. Runner-matched: the
  active line names what actually drives, and a notable big-model state takes
  the info pair."""
  source, active_name, other_name = model_info()
  state = big_model_state()
  _, _, carry_display = carrying_model()
  if carry_display is None:
    big = get_selected_bundle(ui_state.params, "chestnut")
    carry_display = big.displayName if big else default_model_name("chestnut")
  active_text = (carry_display or active_name).lower()
  provisioning = big_model_progress()
  if provisioning is not None:
    stage, frac, msg = provisioning
    if stage == 'failed':
      return active_text, tr("big model"), msg or tr("unavailable")
    # "waiting for jetlink" says more than "connect 0%"; no percentage for a stage
    # with nothing to measure
    detail = msg or tr(stage)
    return active_text, tr("big model"), f"{detail} {frac * 100:.0f}%" if frac > 0 else detail
  if standin := standin_model():
    # the last model the Jetson built drives until the pick is downloaded and built
    return active_text, tr("big model"), tr("{} for now").format(standin.lower())
  if state == 'failed':
    return active_text, tr("big model"), tr("unavailable")
  if state == 'loading':
    return active_text, tr("big model"), tr("getting ready")
  header = tr("small model") if source == "chestnut" else tr("big model")
  return active_text, header, other_name.lower()


class CurrentModelInfo(Widget):
  def __init__(self):
    super().__init__()

    self.set_rect(rl.Rectangle(0, 0, 360, 180))

    header_color = rl.Color(255, 255, 255, int(255 * 0.9))
    subheader_color = rl.Color(255, 255, 255, int(255 * 0.9 * 0.65))
    max_width = int(self._rect.width - 20)
    self.current_model_header = UnifiedLabel(tr("active model"), 48, max_width=max_width, text_color=header_color, font_weight=FontWeight.DISPLAY)
    default_text = tr("{} (Default)").format(DEFAULT_MODEL).lower()
    self.current_model_text = UnifiedLabel(default_text, 32, max_width=max_width, text_color=subheader_color, font_weight=FontWeight.ROMAN, scroll=True)

    self.info_header = UnifiedLabel(tr("cache size"), 48, max_width=max_width, text_color=header_color, font_weight=FontWeight.DISPLAY)
    self.info_text = UnifiedLabel("0 mb", 32, max_width=max_width, text_color=subheader_color, font_weight=FontWeight.ROMAN)

  def _render(self, _):
    self.current_model_header.set_position(self._rect.x + 20, self._rect.y - 10)
    self.current_model_header.render()

    self.current_model_text.set_position(self._rect.x + 20, self._rect.y + 68 - 25)
    self.current_model_text.render()

    self.info_header.set_position(self._rect.x + 20, self._rect.y + 114 - 30)
    self.info_header.render()

    self.info_text.set_position(self._rect.x + 20, self._rect.y + 161 - 25)
    self.info_text.render()

class ModelsLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self.focused_widget = None
    self._selection_source = None

    self.current_model_info = CurrentModelInfo()
    self._download_progress = "."
    self._download_frame = 0
    self._was_downloading = False

    self.link_toggle = AcceleratorLinkToggle()

    self.select_model_btn = BigButton(tr("select model"))
    self.select_model_btn.set_click_callback(self._show_folders)

    self.cancel_download_btn = BigButton(tr("cancel download"))
    self.cancel_download_btn.set_click_callback(lambda: ui_state.params.remove("ModelManager_DownloadRef"))

    self.main_items = [self.current_model_info, self.select_model_btn, self.cancel_download_btn]
    self._scroller.add_widgets(self.main_items)

  @property
  def model_manager(self):
    return ui_state.sm["modelManagerSP"]

  def _get_grouped_bundles(self, favorites = None):
    bundles = self.model_manager.availableBundles
    folders = {}
    for bundle in bundles:
      folder = next((override.value for override in bundle.overrides if override.key == "folder"), "")
      folders.setdefault(folder, []).append(bundle)

    if favorites:
      for fav_bundle in [bundle for bundle in bundles if bundle.ref in favorites]:
        folders.setdefault("favorites", []).append(fav_bundle)

    return folders

  def _push_selection_view(self, items):
    scroller = NavScroller()
    scroller._scroller.add_widgets(items)
    gui_app.push_widget(scroller)

  def _show_folders(self):
    self.focused_widget = self.select_model_btn
    self._selection_source = active_source()

    favs = ui_state.params.get("ModelManager_Favs")
    favorites = set(favs.split(';')) if favs else set()

    folders = self._get_grouped_bundles(favorites)
    folder_buttons = []
    default_btn = BigButton(tr("{} (Default)").format(DEFAULT_MODEL).lower())
    default_btn.set_click_callback(self._select_default)
    folder_buttons.append(default_btn)

    for folder in sorted(folders.keys(), key=lambda f: max((bundle.index for bundle in folders[f]), default=-1), reverse=True):
      if folder.lower() in ["release models", "master models", "favorites"]:
        btn = BigButton(folder.lower())
        btn.set_click_callback(lambda f=folder: self._select_folder(f))
        if folder.lower() == "favorites":
          folder_buttons.insert(0, btn)
        else:
          folder_buttons.append(btn)
    self._push_selection_view(folder_buttons)

  def _pop_to_main(self):
    gui_app.pop_widgets_to(self)

  def _select_model(self, bundle):
    ui_state.params.put("ModelManager_DownloadRef", bundle.ref)
    self._pop_to_main()

  def _select_default(self):
    source = self._selection_source or active_source()
    if source in ACTIVE_BUNDLE_KEYS:
      ui_state.params.remove(ACTIVE_BUNDLE_KEYS[source])
    self._pop_to_main()

  def _select_folder(self, folder_name):
    favs = ui_state.params.get("ModelManager_Favs")
    favorites = set(favs.split(';')) if favs else set()

    folders = self._get_grouped_bundles(favorites)
    bundles = sorted(folders.get(folder_name, []), key=lambda b: b.index, reverse=True)

    btns = []
    for bundle in bundles:
      txt = bundle.displayName.lower()
      btn = BigButton(txt)
      btn.set_click_callback(lambda b=bundle: self._select_model(b))
      btns.append(btn)
    self._push_selection_view(btns)

  def hide_event(self):
    super().hide_event()
    if self._was_downloading:
      device.set_override_interactive_timeout(None)
      self._was_downloading = False

  def _update_state(self):
    super()._update_state()

    self.select_model_btn.set_enabled(ui_state.is_offroad())
    self.cancel_download_btn.set_visible(False)
    self.current_model_info.current_model_header._shimmer = False
    self.current_model_info.info_header._shimmer = False

    manager = self.model_manager
    self._download_frame += 1
    should_update = self._download_frame % (gui_app.target_fps / 2) == 0
    if should_update:
      self._download_progress = self._download_progress + "." if len(self._download_progress) < 3 else ""
      # present() and unavailable_reason() read sysfs, so they ride this half-second tick
      self.link_toggle.refresh()
      self.link_toggle.set_visible(link_toggle_meaningful())

    is_downloading = (manager.selectedBundle
                      and manager.selectedBundle.status == custom.ModelManagerSP.DownloadStatus.downloading)
    if self._was_downloading and not is_downloading:
      device.set_override_interactive_timeout(None)
    self._was_downloading = is_downloading

    self.current_model_info.current_model_header.set_text(tr("active model"))
    model_text = manager.activeBundle.displayName.lower() if manager.activeBundle.ref else tr("{} (Default)").format(DEFAULT_MODEL).lower()
    self.current_model_info.current_model_text.set_text(model_text)
    self.current_model_info.info_header.set_text(tr("cache size"))
    self.current_model_info.info_text.set_text(f"{ModelsLayout.calculate_cache_size():.2f} MB")

    if manager.selectedBundle and manager.selectedBundle.status == custom.ModelManagerSP.DownloadStatus.failed:
      self.current_model_info.info_header.set_text(tr("error") + self._download_progress)
      self.current_model_info.info_text.set_text(tr("download failed"))

    elif manager.selectedBundle and manager.selectedBundle.status == custom.ModelManagerSP.DownloadStatus.downloading:
      self.cancel_download_btn.set_visible(True)
      device.set_override_interactive_timeout(5)
      progress = 0.0
      count = 0
      for model in manager.selectedBundle.models:
        count += 1
        p = model.artifact.downloadProgress
        if p.status == custom.ModelManagerSP.DownloadStatus.downloading:
          progress += p.progress
        elif p.status in (custom.ModelManagerSP.DownloadStatus.downloaded,
                          custom.ModelManagerSP.DownloadStatus.cached):
          progress += 100.0

      self.current_model_info.current_model_header.set_text(tr("downloading"))
      self.current_model_info.current_model_header._shimmer = True
      self.current_model_info.current_model_text.set_text(f"{manager.selectedBundle.internalName.lower()}")
      self.current_model_info.info_header.set_text(tr("progress") + self._download_progress)
      self.current_model_info.info_header._shimmer = True
      self.current_model_info.info_text.set_text(f"{progress/count:.2f}%")

