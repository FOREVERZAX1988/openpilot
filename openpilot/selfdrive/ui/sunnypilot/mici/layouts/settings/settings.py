"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

SP settings entry for mici. Lives inside the settings/ package because the SP
panel modules (navigation, osm, storage, bluetooth, vehicle, carrot) are
submodules of the same package; a top-level layouts/settings.py module would be
shadowed by this package. The re-export in __init__.py keeps the historical
``from ...layouts.settings import SettingsLayoutSP`` import working.
"""
from openpilot.selfdrive.ui.mici.layouts.settings import settings as OP
from openpilot.selfdrive.ui.mici.layouts.settings.settings import SettingsBigButton
from openpilot.selfdrive.ui.mici.widgets.button import BigCircleButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog, BigDialog
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.cruise import CruiseLayoutMici
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.developer import DeveloperLayoutMiciSP
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.display import DisplayLayoutMici
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.models import ModelsLayoutMici
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings.bluetooth import BluetoothLayoutMici
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings.navigation import NavigationLayoutMici
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings.osm import OSMLayoutMici
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings.storage import StorageLayoutMici
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings.vehicle import VehicleLayoutMici
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.software import SoftwareLayoutSP
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.steering import SteeringLayoutMici
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.sunnylink import SunnylinkLayoutMici
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.trips import TripsLayoutMici
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.visuals import VisualsLayoutMici
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.sunnypilot.ui_state import set_always_offroad
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr

# the alpha switch moves to Cruise > alpha longitudinal. Swapped before the base layout builds it, so
# the upstream panel is never constructed and its ui_state callbacks (a full params pass each) never
# register.
OP.DeveloperLayoutMici = DeveloperLayoutMiciSP
OP.SoftwareLayoutMici = SoftwareLayoutSP

SP_ICON = "../../sunnypilot/selfdrive/assets/offroad"
BIG_ICON_SIZE = 110


class SunnylinkBigButton(SettingsBigButton):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._label.set_font_weight(FontWeight.BOLD)

  def _get_label_font_size(self):
    return 56


class SettingsLayoutSP(OP.SettingsLayout):
  def __init__(self):
    OP.SettingsLayout.__init__(self)

    # by label: an index mis-wires silently if the base list is ever reordered
    self._replace_panel("software", SoftwareLayoutSP())

    self.icon_offroad_enable = gui_app.texture("../../sunnypilot/selfdrive/assets/icons_mici/always_offroad.png", BIG_ICON_SIZE,
                                               BIG_ICON_SIZE)
    self.icon_offroad_disable = gui_app.texture("../../sunnypilot/selfdrive/assets/icons_mici/disable_offroad.png", BIG_ICON_SIZE,
                                                BIG_ICON_SIZE)
    self.icon_offroad_slider = gui_app.texture("icons_mici/settings/device/lkas.png", BIG_ICON_SIZE, BIG_ICON_SIZE)

    def open_panel(panel):
      return lambda: gui_app.push_widget(panel)

    # SP panels, keyed by their lowercase mici label
    panels = {
      "bluetooth": (BluetoothLayoutMici, gui_app.texture("icons/bluetooth.png", 64, 64)),
      "models": (ModelsLayoutMici, gui_app.texture(f"{SP_ICON}/icon_models.png", 64, 64)),
      "storage": (StorageLayoutMici, gui_app.texture(f"{SP_ICON}/icon_models.png", 64, 64)),
      "cruise": (CruiseLayoutMici, gui_app.texture(f"{SP_ICON}/icon_vehicle.png", 64, 64)),
      "steering": (SteeringLayoutMici, gui_app.texture(f"{SP_ICON}/icon_lateral.png", 64, 64)),
      "display": (DisplayLayoutMici, gui_app.texture(f"{SP_ICON}/icon_display.png", 64, 64)),
      "visuals": (VisualsLayoutMici, gui_app.texture(f"{SP_ICON}/icon_visuals.png", 64, 64)),
      "osm": (OSMLayoutMici, gui_app.texture(f"{SP_ICON}/icon_map.png", 64, 64)),
      "navigation": (NavigationLayoutMici, gui_app.texture(f"{SP_ICON}/icon_map.png", 64, 64)),
      "trips": (TripsLayoutMici, gui_app.texture(f"{SP_ICON}/icon_trips.png", 64, 64)),
      "vehicle": (VehicleLayoutMici, gui_app.texture(f"{SP_ICON}/icon_vehicle.png", 64, 64)),
    }
    sp_buttons = {}
    for label, (panel_cls, icon) in panels.items():
      btn = SettingsBigButton(tr(label), "", icon)
      btn.set_click_callback(open_panel(panel_cls()))
      sp_buttons[label] = btn

    # Carrot is its own subsystem built by its own panel modules; skipped if they
    # are absent (e.g. stripped trees), same fallback idea as the Big GUI import.
    try:
      from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings.carrot import CarrotLayoutMici
      carrot_btn = SettingsBigButton(tr("carrot"), "", gui_app.texture(f"{SP_ICON}/icon_map.png", 64, 64))
      carrot_btn.set_click_callback(open_panel(CarrotLayoutMici()))
      sp_buttons["carrot"] = carrot_btn
    except ImportError:
      cloudlog.warning("mici settings: carrot panel not available, skipping")

    sunnylink_panel = SunnylinkLayoutMici()
    sunnylink_btn = SunnylinkBigButton(tr("sunnylink"), "", gui_app.texture("../../sunnypilot/selfdrive/assets/icons_mici/sunnylink.png", 76, 44))
    sunnylink_btn.set_click_callback(lambda: gui_app.push_widget(sunnylink_panel))
    sp_buttons["sunnylink"] = sunnylink_btn

    always_offroad_desc = tr("Keeps the device offroad while the car is on, so zoompilot won't engage.\n" +
                             "Settings that need the car off can be changed.")

    # onroad: enable button sits at the front (left of toggles)
    self._enable_offroad_btn_onroad = BigCircleButton(self.icon_offroad_enable, red=True, title=tr("enable always offroad"),
                                                      description=always_offroad_desc)
    self._enable_offroad_btn_onroad.set_click_callback(lambda: self._handle_always_offroad(True))
    self._enable_offroad_btn_onroad.set_visible(lambda: ui_state.started and not ui_state.always_offroad)

    # offroad: enable button sits at the end (right of developer)
    self._enable_offroad_btn_offroad = BigCircleButton(self.icon_offroad_enable, red=True, title=tr("enable always offroad"),
                                                       description=always_offroad_desc)
    self._enable_offroad_btn_offroad.set_click_callback(lambda: self._handle_always_offroad(True))
    self._enable_offroad_btn_offroad.set_visible(lambda: not ui_state.started and not ui_state.always_offroad)

    self._disable_offroad_btn = BigCircleButton(self.icon_offroad_disable, red=False, title=tr("exit always offroad"),
                                                description=tr("Ends always offroad, so zoompilot can engage again."))
    self._disable_offroad_btn.set_click_callback(lambda: self._handle_always_offroad(False))
    self._disable_offroad_btn.set_visible(lambda: ui_state.always_offroad)

    # panel order mirrors the Big GUI sidebar (driving is mici-specific and stays
    # first); every entry must resolve to a button or the layout is incomplete
    order = ["driving", "device", "network", "bluetooth", "sunnylink", "toggles", "software", "models", "storage",
             "steering", "cruise", "visuals", "display", "osm", "navigation", "carrot", "trips", "vehicle",
             "firehose", "imu calibration", "developer"]

    buttons = {btn.text: btn for btn in self._scroller.items if hasattr(btn, "text")}
    buttons.update(sp_buttons)

    items = []
    for label in order:
      btn = buttons.get(tr(label))
      if btn is None:
        cloudlog.warning(f"mici settings: no panel button labelled {label!r}")
        continue
      items.append(btn)

    # front slots (only one ever visible at a time): exit-always-offroad, then enable-onroad
    items.insert(0, self._enable_offroad_btn_onroad)
    items.insert(0, self._disable_offroad_btn)
    # end slot: enable-offroad (right of developer)
    items.append(self._enable_offroad_btn_offroad)

    self._scroller.items.clear()
    for item in items:
      self._scroller.add_widget(item)

  def _replace_panel(self, label: str, panel) -> None:
    btn = next((btn for btn in self._scroller.items if btn.text == label), None)
    if btn is None:
      cloudlog.warning(f"mici settings: no panel button labelled {label!r}")
      return
    btn.set_click_callback(lambda: gui_app.push_widget(panel))

  def _handle_always_offroad(self, enable: bool):

    def _set_offroad_status(status: bool):
      if not ui_state.engaged:
        set_always_offroad(ui_state.params, status)
        ui_state.always_offroad = status

    if not enable:
      dlg = BigConfirmationDialog(tr("slide to exit always offroad"), self.icon_offroad_slider, red=False,
                                  confirm_callback=lambda: _set_offroad_status(False))
    else:
      if ui_state.engaged:
        gui_app.push_widget(BigDialog(tr("disengage to enable always offroad"), "", ))
        return

      dlg = BigConfirmationDialog(tr("slide to force offroad"), self.icon_offroad_slider, red=True,
                                  confirm_callback=lambda: _set_offroad_status(True))
    gui_app.push_widget(dlg)
