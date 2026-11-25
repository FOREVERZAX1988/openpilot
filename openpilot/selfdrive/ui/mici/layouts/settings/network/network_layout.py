from openpilot.selfdrive.ui.mici.layouts.settings.network import EsimNetworkButton, WifiNetworkButton
from openpilot.selfdrive.ui.mici.layouts.settings.network.esim_ui import EsimUI
from openpilot.selfdrive.ui.mici.layouts.settings.network.wifi_ui import WifiUIMici
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiToggle, BigParamControl, BigToggle
from openpilot.selfdrive.ui.mici.widgets.dialog import BigInputDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.cellular_manager import CellularManager
from openpilot.system.ui.lib.wifi_manager import WifiManager, Network, MeteredType
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller


class NetworkLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    self._wifi_manager = WifiManager()
    self._wifi_manager.set_active(False)
    self._wifi_ui = WifiUIMici(self._wifi_manager)

    self._wifi_manager.add_callbacks(
      networks_updated=self._on_network_updated,
      need_auth=self._on_need_auth,
    )

    # ******** Tethering ********
    def tethering_toggle_callback(checked: bool):
      self._tethering_toggle_btn.set_enabled(False)
      self._tethering_password_btn.set_enabled(False)
      self._network_metered_btn.set_enabled(False)
      self._wifi_manager.set_tethering_active(checked)

    self._tethering_toggle_btn = BigToggle(tr("enable tethering"), "", toggle_callback=tethering_toggle_callback,
                                           description=tr("Share the device's internet connection through a Wi-Fi hotspot."))

    def tethering_password_callback(password: str):
      if password:
        self._tethering_toggle_btn.set_enabled(False)
        self._tethering_password_btn.set_enabled(False)
        self._wifi_manager.set_tethering_password(password)

    def tethering_password_clicked():
      tethering_password = self._wifi_manager.tethering_password
      # WPA2 passphrases are 8 to 63 characters, NetworkManager rejects anything else
      dlg = BigInputDialog(tr("enter password..."), tethering_password, minimum_length=8, mask=True,
                           confirm_callback=tethering_password_callback, text_validator=lambda text: len(text) <= 63)
      gui_app.push_widget(dlg)

    txt_tethering = gui_app.texture("icons_mici/settings/network/tethering.png", 64, 54)
    self._tethering_password_btn = BigButton(tr("tethering password"), "", txt_tethering)
    self._tethering_password_btn.set_click_callback(tethering_password_clicked)

    # ******** Network Metered ********
    def network_metered_callback(value: str):
      self._network_metered_btn.set_enabled(False)
      metered = {
        tr('default'): MeteredType.UNKNOWN,
        tr('metered'): MeteredType.YES,
        tr('unmetered'): MeteredType.NO
      }.get(value, MeteredType.UNKNOWN)
      self._wifi_manager.set_current_network_metered(metered)

    # TODO: signal for current network metered type when changing networks, this is wrong until you press it once
    # TODO: disable when not connected
    self._network_metered_btn = BigMultiToggle(tr("network usage"), [tr("default"), tr("metered"), tr("unmetered")], select_callback=network_metered_callback,
                                               description=tr("Metered prevents large uploads on this Wi-Fi connection. Default uses the network's detected " +
                                                           "setting."))
    self._network_metered_btn.set_enabled(False)

    self._wifi_button = WifiNetworkButton(self._wifi_manager)
    self._wifi_button.set_click_callback(lambda: gui_app.push_widget(self._wifi_ui))

    # ******** Hidden network ********
    self._connecting_hidden_ssid: str | None = None
    self._hidden_network_btn = BigButton(tr("hidden network"), tr("connect"),
                                         description=tr("Connect to a Wi-Fi network that does not broadcast its name."))
    self._hidden_network_btn.set_click_callback(self._connect_to_hidden_network)

    # ******** eSIM ********
    self._cellular_manager = CellularManager()
    self._esim_ui = EsimUI(
      self._cellular_manager,
      lambda: not ui_state.prime_state.is_full_prime(),
    )
    self._esim_button = EsimNetworkButton(self._cellular_manager)
    self._esim_button.set_click_callback(lambda: gui_app.push_widget(self._esim_ui))

    # ******** Advanced settings ********
    # ******** Roaming toggle ********
    self._roaming_btn = BigParamControl(tr("enable roaming"), "GsmRoaming", description=tr("Allow cellular data roaming."))

    # ******** APN settings ********
    self._apn_btn = BigButton(tr("apn settings"), tr("edit"),
                              description=tr("Set the access point name required by your cellular carrier. Leave blank for automatic configuration."))
    self._apn_btn.set_click_callback(self._edit_apn)

    # ******** Cellular metered toggle ********
    self._cellular_metered_btn = BigParamControl(tr("cellular metered"), "GsmMetered", description=tr("Prevent large uploads over the cellular connection."))

    # Main scroller ----------------------------------
    self._scroller.add_widgets([
      self._wifi_button,
      self._hidden_network_btn,
      self._esim_button,
      self._network_metered_btn,
      self._tethering_toggle_btn,
      self._tethering_password_btn,
      # /* Advanced settings
      self._roaming_btn,
      self._apn_btn,
      self._cellular_metered_btn,
      # */
    ])

  def _update_state(self):
    super()._update_state()

    show_cell_settings = not ui_state.prime_state.is_full_prime()
    self._wifi_manager.set_ipv4_forward(show_cell_settings)
    self._roaming_btn.set_visible(show_cell_settings)
    self._apn_btn.set_visible(show_cell_settings)
    self._cellular_metered_btn.set_visible(show_cell_settings)

  def show_event(self):
    super().show_event()
    self._wifi_manager.set_active(True)

    # Process wifi and esim callbacks while at any point in the nav stack
    gui_app.add_nav_stack_tick(self._wifi_manager.process_callbacks)
    gui_app.add_nav_stack_tick(self._cellular_manager.process_callbacks)

  def hide_event(self):
    super().hide_event()
    self._wifi_manager.set_active(False)

    gui_app.remove_nav_stack_tick(self._wifi_manager.process_callbacks)
    gui_app.remove_nav_stack_tick(self._cellular_manager.process_callbacks)

  def _connect_to_hidden_network(self):
    def connect_hidden(ssid: str):
      if not ssid:
        return

      def enter_password(password: str):
        # WPA2 passphrases are 8 to 63 characters, NetworkManager rejects anything else
        self._connecting_hidden_ssid = ssid
        self._wifi_manager.connect_to_network(ssid, password, hidden=True)

      dlg = BigInputDialog(tr("enter password..."), "", minimum_length=0, mask=True,
                           confirm_callback=enter_password, text_validator=lambda text: len(text) <= 63)
      gui_app.push_widget(dlg)

    dlg = BigInputDialog(tr("enter SSID..."), minimum_length=1, confirm_callback=connect_hidden)
    gui_app.push_widget(dlg)

  def _on_need_auth(self, ssid, incorrect_password=True):
    # a hidden network is not in the scan results, so its wrong password feedback
    # shakes the hidden network button instead of a WifiButton row
    if incorrect_password and ssid == self._connecting_hidden_ssid:
      self._connecting_hidden_ssid = None
      self._hidden_network_btn.trigger_shake()

  def _edit_apn(self):
    def update_apn(apn: str):
      apn = apn.strip()
      if apn == "":
        ui_state.params.remove("GsmApn")
      else:
        ui_state.params.put("GsmApn", apn)

    current_apn = ui_state.params.get("GsmApn") or ""
    dlg = BigInputDialog(tr("enter APN..."), current_apn, minimum_length=0, mask=True, confirm_callback=update_apn)
    gui_app.push_widget(dlg)

  def _on_network_updated(self, networks: list[Network]):
    # Update tethering state
    tethering_active = self._wifi_manager.is_tethering_active()
    # TODO: use real signals (like activated/settings changed, etc.) to speed up re-enabling buttons
    self._tethering_toggle_btn.set_enabled(True)
    self._tethering_password_btn.set_enabled(True)
    self._network_metered_btn.set_enabled(lambda: not tethering_active and bool(self._wifi_manager.ipv4_address))
    self._tethering_toggle_btn.set_checked(tethering_active)

    # Update network metered
    self._network_metered_btn.set_value(
      {
        MeteredType.UNKNOWN: tr('default'),
        MeteredType.YES: tr('metered'),
        MeteredType.NO: tr('unmetered')
      }.get(self._wifi_manager.current_network_metered, tr('default')))
