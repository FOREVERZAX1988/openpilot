"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Mici vehicle panel: CarPlatformBundle selection plus the per-brand toggles the
Big GUI vehicle page offers (toyota/hyundai/subaru/tesla; the other brands have
no settings upstream). The Big GUI TreeOptionDialog degrades to a make -> model
BigButton list flow on the small screen.
"""
import json
import os

from opendbc.car.hyundai.values import CAR as HYUNDAI_CAR, UNSUPPORTED_LONGITUDINAL_CAR
from opendbc.car.subaru.values import CAR as SUBARU_CAR, SubaruFlags
from opendbc.sunnypilot.car.tesla.values import TeslaFlagsSP

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiParamToggle, BigParamControl, BigToggle, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller

CAR_LIST_JSON = os.path.join(BASEDIR, "openpilot", "sunnypilot", "selfdrive", "car", "car_list.json")

INFO_ICON = "icons_mici/setup/green_info.png"


class VehicleLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._platforms = self._load_platforms()
    self._brand = ""
    self._brand_toggles: list = []
    self._toyota_enforce_toggle: BigToggle | None = None
    self._param_toggles: list[BigParamControl | BigMultiParamToggle] = []

    self._vehicle_btn = BigButton(tr("Vehicle"), "", scroll=True,
                                  description=tr("Select vehicle to force fingerprint manually."))
    self._vehicle_btn.set_click_callback(self._on_vehicle_clicked)

    self._scroller.add_widget(self._vehicle_btn)
    self._refresh_vehicle_btn()

  # ------------------------------------------------------------------ helpers
  @staticmethod
  def _load_platforms() -> dict:
    try:
      with open(CAR_LIST_JSON) as car_list_json:
        return json.load(car_list_json)
    except Exception:
      return {}

  @staticmethod
  def get_brand() -> str:
    if bundle := ui_state.params.get("CarPlatformBundle"):
      return bundle.get("brand", "")
    elif ui_state.CP is not None and ui_state.CP.carFingerprint != "MOCK":
      return ui_state.CP.brand
    return ""

  def _refresh_vehicle_btn(self):
    # same three states as Big GUI platform_selector.refresh()
    if bundle := ui_state.params.get("CarPlatformBundle"):
      self._vehicle_btn.set_text(bundle.get("name", ""))
      self._vehicle_btn.set_value(tr("manually selected fingerprint"))
    elif ui_state.CP is not None and ui_state.CP.carFingerprint != "MOCK":
      self._vehicle_btn.set_text(ui_state.CP.carFingerprint)
      self._vehicle_btn.set_value(tr("fingerprinted automatically"))
    else:
      self._vehicle_btn.set_text(tr("No vehicle selected"))
      self._vehicle_btn.set_value(tr("not fingerprinted"))

  # ----------------------------------------------------------------- selection
  def _on_vehicle_clicked(self):
    # parity with Big GUI: a manual bundle is removed on tap, otherwise open the picker
    if ui_state.params.get("CarPlatformBundle"):
      ui_state.params.remove("CarPlatformBundle")
      self._refresh_vehicle_btn()
    else:
      gui_app.push_widget(BrandPickerPage(self))

  def _select_platform(self, name: str):
    data = self._platforms.get(name)
    if not data:
      return
    offroad_msg = (tr("This setting will take effect immediately.") if ui_state.is_offroad()
                   else tr("This setting will take effect once the device enters offroad state."))

    def on_confirm():
      ui_state.params.put("CarPlatformBundle", {**data, "name": name})
      gui_app.pop_widgets_to(self)
    gui_app.push_widget(BigConfirmationDialog(offroad_msg, gui_app.texture(INFO_ICON, 64, 64), on_confirm))

  # ------------------------------------------------------------ brand toggles
  def _rebuild_brand_items(self, brand: str):
    builders = {
      "toyota": self._build_toyota,
      "hyundai": self._build_hyundai,
      "subaru": self._build_subaru,
      "tesla": self._build_tesla,
    }
    self._brand_toggles = builders[brand]() if brand in builders else []
    self._toyota_enforce_toggle = None
    self._param_toggles = [w for w in self._brand_toggles if isinstance(w, (BigParamControl, BigMultiParamToggle))]

    self._scroller.items[:] = [self._vehicle_btn]
    self._scroller.add_widgets(self._brand_toggles)

  def _build_toyota(self) -> list:
    self._toyota_enforce_toggle = BigToggle(
      tr("Enforce Factory Longitudinal Control"), "",
      initial_state=ui_state.params.get_bool("ToyotaEnforceStockLongitudinal"),
      toggle_callback=self._on_enforce_stock_long,
      description=tr("sunnypilot will not take over control of gas and brakes. Factory Toyota longitudinal control will be used."))
    self._toyota_enforce_toggle.set_enabled(lambda: not ui_state.engaged)

    sng = BigParamControl(tr("Stop and Go Hack (Alpha)"), "ToyotaStopAndGoHack",
                          description=tr("sunnypilot will allow some Toyota/Lexus cars to auto resume during stop and go traffic. " +
                                         "This feature is only applicable to certain models that are able to use longitudinal control. " +
                                         "This is an alpha feature. Use at your own risk."))
    sng.set_enabled(lambda: not ui_state.engaged)

    auto_hold = BigParamControl(tr("Toyota: Auto Brake Hold FOR TSS2 HYBRID CARS"), "ToyotaAutoHold",
                                description=tr("Use the vehicle's auto brake hold feature on supported TSS2 hybrid Toyotas."))
    auto_hold.set_enabled(lambda: not ui_state.engaged)

    bsm = BigParamControl(tr("Toyota: Prius TSS2 BSM and some tssp"), "ToyotaEnhancedBsm",
                          description=tr("Enable enhanced blind-spot monitoring behavior for certain Prius TSS2 and TSS-P Toyotas."))
    bsm.set_enabled(lambda: not ui_state.engaged)

    tss2_long = BigParamControl(tr("Toyota: custom longitudinal for TSS2"), "ToyotaTSS2Long",
                                description=tr("Use a custom longitudinal tuning profile for TSS2 Toyota vehicles."))
    tss2_long.set_enabled(lambda: not ui_state.engaged)

    drive_mode = BigParamControl(tr("Enable drive mode btn link"), "ToyotaDriveMode",
                                 description=tr("Link the Toyota drive-mode button (ECO/NORMAL/SPORT) into sunnypilot logic."))

    smooth = BigParamControl(tr("TSS2 Smooth Longitudinal (Alpha)"), "ToyotaTSS2Smooth",
                             description=tr("Enable smoother longitudinal control for TSS2 vehicles. " +
                                            "Uses a custom speed-dependent integral gain curve for smoother traffic driving."))
    smooth.set_enabled(lambda: not ui_state.engaged)

    return [GreyBigButton(tr("Toyota"), ""), self._toyota_enforce_toggle, sng, auto_hold, bsm, tss2_long, drive_mode, smooth]

  def _build_hyundai(self) -> list:
    tuning = BigMultiParamToggle(tr("Custom Longitudinal Tuning"), "HyundaiLongitudinalTuning",
                                 [tr("Off"), tr("Dynamic"), tr("Predictive")],
                                 description=tr("Select the custom longitudinal tuning profile for supported Hyundai vehicles."))
    return [GreyBigButton(tr("Hyundai"), ""), tuning]

  def _build_subaru(self) -> list:
    sng = BigParamControl(tr("Stop and Go (Beta)"), "SubaruStopAndGo",
                          description=tr("Experimental feature to enable auto-resume during stop-and-go for certain supported Subaru platforms."))
    sng_manual = BigParamControl(tr("Stop and Go for Manual Parking Brake (Beta)"), "SubaruStopAndGoManualParkingBrake",
                                 description=tr("Experimental feature to enable stop and go for Subaru Global models with manual handbrake. " +
                                                "Models with electric parking brake should keep this disabled. Thanks to martinl for this implementation!"))
    return [GreyBigButton(tr("Subaru"), ""), sng, sng_manual]

  def _build_tesla(self) -> list:
    is_metric = ui_state.is_metric
    coop_kmh, oem_kmh = 23, 48
    coop_speed = coop_kmh if is_metric else round(coop_kmh * 0.621371)
    oem_speed = oem_kmh if is_metric else round(oem_kmh * 0.621371)
    unit = tr("km/h") if is_metric else tr("mph")

    coop = BigParamControl(tr("Cooperative Steering (Beta)"), "TeslaCoopSteering",
                           description=tr("Warning: May experience steering oscillations below {speed} {unit} during turns, " +
                                          "recommend disabling this feature if you experience these.").format(speed=oem_speed, unit=unit) +
                                          "\n" +
                                          tr("Allows the driver to provide limited steering input while openpilot is engaged.") +
                                          "\n" +
                                          tr("Only works above {speed} {unit}.").format(speed=coop_speed, unit=unit))
    coop.set_enabled(lambda: ui_state.is_offroad())

    mads = BigMultiParamToggle(tr("MADS Screen Activation"), "TeslaMadsScreenButton",
                               [tr("Off"), tr("3-Finger"), tr("4-Finger"), tr("5-Finger")],
                               description=tr("Use a multi-finger press on the infotainment screen to toggle MADS. " +
                                              "Selecting a higher finger count may reduce accidental activations. " +
                                              "Note: Setting this to Off will reset your MADS settings to default."))
    return [GreyBigButton(tr("Tesla"), ""), coop, mads]

  def _on_enforce_stock_long(self, state: bool):
    # the actual write happens only after the slider confirm; the toggle visual
    # is resynced from the param in _update_state in both paths
    if not state:
      ui_state.params.put_bool("ToyotaEnforceStockLongitudinal", False)
      ui_state.params.put_bool("OnroadCycleRequested", True)
      return

    def on_confirm():
      ui_state.params.put_bool("ToyotaEnforceStockLongitudinal", True)
      if ui_state.params.get_bool("AlphaLongitudinalEnabled"):
        ui_state.params.put_bool("AlphaLongitudinalEnabled", False)
      ui_state.params.put_bool("ToyotaStopAndGoHack", False)
      ui_state.params.put_bool("ToyotaTSS2Smooth", False)
      ui_state.params.put_bool("OnroadCycleRequested", True)
    gui_app.push_widget(BigConfirmationDialog(tr("Enforce Factory Longitudinal Control"),
                                              gui_app.texture(INFO_ICON, 64, 64), on_confirm))

  # ------------------------------------------------------------------- update
  def _update_state(self):
    super()._update_state()

    self._refresh_vehicle_btn()

    brand = self.get_brand()
    if brand != self._brand:
      self._brand = brand
      self._rebuild_brand_items(brand)

    for toggle in self._param_toggles:
      toggle.refresh()

    self._update_brand_gating(brand)

    if self._toyota_enforce_toggle is not None:
      self._toyota_enforce_toggle.set_checked(ui_state.params.get_bool("ToyotaEnforceStockLongitudinal"))

  def _update_brand_gating(self, brand: str):
    bundle = ui_state.params.get("CarPlatformBundle")

    if brand == "hyundai":
      alpha_long_available = False
      if bundle:
        platform = bundle.get("platform")
        try:
          alpha_long_available = platform in HYUNDAI_CAR and HYUNDAI_CAR[platform] not in set().union(*UNSUPPORTED_LONGITUDINAL_CAR.values())
        except Exception:
          alpha_long_available = False
      elif ui_state.CP is not None:
        alpha_long_available = ui_state.CP.alphaLongitudinalAvailable

      tuning = self._param_toggles[0] if self._param_toggles else None
      if tuning is not None:
        tuning.set_visible(alpha_long_available)
        tuning.set_enabled(ui_state.is_offroad() and ui_state.has_longitudinal_control)

    elif brand == "subaru":
      has_stop_and_go = False
      if bundle:
        try:
          platform = bundle.get("platform")
          if platform in SUBARU_CAR:
            has_stop_and_go = not (SUBARU_CAR[platform].config.flags & (SubaruFlags.GLOBAL_GEN2 | SubaruFlags.HYBRID))
        except Exception:
          has_stop_and_go = False
      elif ui_state.CP is not None:
        has_stop_and_go = not (ui_state.CP.flags & (SubaruFlags.GLOBAL_GEN2 | SubaruFlags.HYBRID))

      for toggle in self._param_toggles:
        toggle.set_enabled(has_stop_and_go and ui_state.is_offroad())

    elif brand == "tesla":
      coop = self._param_toggles[0] if len(self._param_toggles) > 0 else None
      mads = self._param_toggles[1] if len(self._param_toggles) > 1 else None
      if coop is not None:
        coop.set_enabled(ui_state.is_offroad())
      if mads is not None:
        has_vehicle_bus = ui_state.CP_SP is not None and bool(ui_state.CP_SP.flags & TeslaFlagsSP.HAS_VEHICLE_BUS)
        mads.set_visible(has_vehicle_bus)
        mads.set_enabled(ui_state.is_offroad())


class BrandPickerPage(NavScroller):
  def __init__(self, layout: VehicleLayoutMici):
    super().__init__()
    self._scroller.add_widget(GreyBigButton(tr("Select a vehicle"), tr("scroll to continue")))
    makes = sorted({p.get('make') for p in layout._platforms.values() if p.get('make')})
    for make in makes:
      btn = BigButton(make, "", scroll=True)
      btn.set_click_callback(lambda m=make: gui_app.push_widget(ModelPickerPage(layout, m)))
      self._scroller.add_widget(btn)


class ModelPickerPage(NavScroller):
  def __init__(self, layout: VehicleLayoutMici, make: str):
    super().__init__()
    self._layout = layout
    self._scroller.add_widget(GreyBigButton(make, tr("scroll to continue")))
    for name in sorted(n for n, p in layout._platforms.items() if p.get('make') == make):
      btn = BigButton(name, "", scroll=True)
      btn.set_click_callback(lambda n=name: layout._select_platform(n))
      self._scroller.add_widget(btn)
