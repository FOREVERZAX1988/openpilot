from collections.abc import Callable
from openpilot.common.time_helpers import system_time_valid
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigToggle, BigParamControl, BigCircleParamControl, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog, BigInputDialog, BigConfirmationCircleButton
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.selfdrive.ui.layouts.settings.common import restart_needed_callback
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.widgets.ssh_key import SshKeyFetcher
from openpilot.selfdrive.ui.widgets.tailscale_dialog import TailscaleDialog


class AlphaLongConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None]):
    super().__init__()

    accept = BigConfirmationCircleButton(tr("enable alpha\nlongitudinal"),
                                         gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 64, 64),
                                         lambda: self.dismiss(on_confirm))

    self._scroller.add_widgets([
      GreyBigButton(tr("enabling alpha longitudinal"), tr("scroll to continue"),
                    gui_app.texture("icons_mici/setup/warning.png", 64, 64)),
      GreyBigButton("", tr("WARNING: alpha longitudinal control may disable Automatic Emergency Braking (AEB)")),
      GreyBigButton("", tr("On this car, openpilot defaults to the stock system's built-in ACC.")),
      GreyBigButton("", tr("Enabling this will switch to openpilot longitudinal control.")),
      GreyBigButton("", tr("Using Experimental mode is recommended with openpilot longitudinal control alpha.")),
      GreyBigButton("", tr("Changing this setting will restart openpilot if the car is powered on.")),
      accept,
    ])


class AgentPasswordConfirmPage(NavScroller):
  def __init__(self, on_confirm: Callable[[], None]):
    super().__init__()

    accept = BigConfirmationCircleButton(tr("reset agent\npassword"),
                                         gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 64, 64),
                                         lambda: self.dismiss(on_confirm))

    self._scroller.add_widgets([
      GreyBigButton(tr("reset agent password"), tr("The web login password will be regenerated."),
                    gui_app.texture("icons_mici/settings/developer/ssh.png", 64, 64)),
      GreyBigButton("", tr("Sessions using the old password stop working once the agent restarts.")),
      accept,
    ])


class DeveloperLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._ssh_fetcher = SshKeyFetcher(ui_state.params)

    def github_username_callback(username: str):
      if username:
        self._ssh_keys_btn.set_value(tr("Loading..."))
        self._ssh_keys_btn.set_enabled(False)

        def on_response(error):
          self._ssh_keys_btn.set_enabled(True)
          if error is None:
            self._ssh_keys_btn.set_value(username)
          else:
            self._ssh_keys_btn.set_value(tr("Not set"))
            gui_app.push_widget(BigDialog("", error))

        self._ssh_fetcher.fetch(username, on_response)
      else:
        self._ssh_fetcher.clear()
        self._ssh_keys_btn.set_value(tr("Not set"))

    def ssh_keys_callback():
      github_username = ui_state.params.get("GithubUsername") or ""
      dlg = BigInputDialog(tr("enter GitHub username..."), github_username, minimum_length=0, confirm_callback=github_username_callback)
      if not system_time_valid():
        dlg = BigDialog("", "Please connect to Wi-Fi to fetch your key.")
        gui_app.push_widget(dlg)
        return
      gui_app.push_widget(dlg)

    txt_ssh = gui_app.texture("icons_mici/settings/developer/ssh.png", 56, 64)
    github_username = ui_state.params.get("GithubUsername") or ""
    self._ssh_keys_btn = BigButton(tr("SSH keys"), tr("Not set") if not github_username else github_username, icon=txt_ssh,
                                   description=tr("Grant SSH access to all public keys in your GitHub settings. Only enter your own username."))
    self._ssh_keys_btn.set_click_callback(ssh_keys_callback)

    # adb, ssh, ssh keys, debug mode, joystick debug mode, longitudinal maneuver mode, ip address
    # ******** Main Scroller ********
    alpha_long_description = tr("Use alpha openpilot longitudinal control instead of stock ACC. This may disable Automatic Emergency Braking (AEB).")
    self._adb_toggle = BigCircleParamControl(gui_app.texture("icons_mici/adb_short.png", 82, 82), "AdbEnabled", icon_offset=(0, 12),
                                             description=tr("Use Android Debug Bridge (ADB) over USB or the network."), title=tr("enable ADB"))
    self._ssh_toggle = BigCircleParamControl(gui_app.texture("icons_mici/ssh_short.png", 82, 82), "SshEnabled", icon_offset=(0, 12),
                                             description=tr("Access the device remotely using your SSH keys."), title=tr("enable SSH"))
    self._tailscale_toggle = BigCircleParamControl(gui_app.texture("icons_mici/ssh_short.png", 82, 82), "TailscaleEnabled",
                                                   toggle_callback=self._on_enable_tailscale, icon_offset=(0, 12),
                                                   description=tr("Remote SSH from anywhere via Tailscale."
                                                                  + " Enable, then scan the pairing QR on the next screen."),
                                                   title=tr("remote SSH"))
    self._tailscale_qr_btn = BigButton(tr("pairing QR code"), tr("show"), icon=txt_ssh,
                                       description=tr("Reopen the Tailscale pairing QR and the SSH address while remote SSH is enabled."))
    self._tailscale_qr_btn.set_click_callback(self._on_show_tailscale_qr)
    self._agent_toggle = BigCircleParamControl(gui_app.texture("icons_mici/settings/developer/ssh.png", 82, 82), "AgentEnabled",
                                               toggle_callback=self._on_enable_agent, icon_offset=(0, 12),
                                               description=tr("Built-in AI agent, offroad only. Browser access on port 5095;"
                                                              + " the password is shown below."),
                                               title=tr("AI agent"))
    self._agent_password_btn = BigButton(tr("AI agent password"),
                                         ui_state.params.get("AgentPassword") or tr("Not set"), icon=txt_ssh,
                                         description=tr("Login password for the agent web page (port 5095). Tap to regenerate."))
    self._agent_password_btn.set_click_callback(self._on_reset_agent_password)
    self._agent_password_set_btn = BigButton(tr("set agent password"), tr("custom"), icon=txt_ssh,
                                             description=tr("Type a custom web login password. "
                                                            + "The change takes effect within a minute, when the agent restarts."))
    self._agent_password_set_btn.set_click_callback(self._on_set_agent_password)
    self._joystick_toggle = BigToggle(tr("joystick debug\nmode"), initial_state=ui_state.params.get_bool("JoystickDebugMode"),
                                      toggle_callback=self._on_joystick_debug_mode, description=tr("Control the car with a joystick for debugging."))
    self._long_maneuver_toggle = BigToggle(tr("longitudinal maneuver mode"), initial_state=ui_state.params.get_bool("LongitudinalManeuverMode"),
                                           toggle_callback=self._on_long_maneuver_mode,
                                           description=tr("Run longitudinal maneuvers for testing gas and brake control."))
    self._lat_maneuver_toggle = BigToggle(tr("lateral maneuver mode"), initial_state=ui_state.params.get_bool("LateralManeuverMode"),
                                          toggle_callback=self._on_lat_maneuver_mode,
                                          description=tr("Run lateral maneuvers for testing steering control."))
    self._alpha_long_toggle = BigToggle(tr("alpha longitudinal"), initial_state=ui_state.params.get_bool("AlphaLongitudinalEnabled"),
                                        toggle_callback=self._on_alpha_long_enabled,
                                        description=alpha_long_description)
    self._navigation_toggle = BigParamControl(tr("navigation (alpha)"), "NavigationEnabled",
                                              description=tr("Turn-by-turn navigation with a route map. Set a destination from comma connect."))
    self._debug_mode_toggle = BigParamControl(tr("ui debug mode"), "ShowDebugInfo",
                                              toggle_callback=lambda checked: (gui_app.set_show_touches(checked), gui_app.set_show_fps(checked)),
                                              description=tr("Show touch locations and the UI frame rate."))

    self._scroller.add_widgets([
      self._adb_toggle,
      self._ssh_toggle,
      self._tailscale_toggle,
      self._tailscale_qr_btn,
      self._agent_toggle,
      self._agent_password_btn,
      self._agent_password_set_btn,
      self._ssh_keys_btn,
      self._joystick_toggle,
      self._long_maneuver_toggle,
      self._lat_maneuver_toggle,
      self._alpha_long_toggle,
      self._debug_mode_toggle,
      self._navigation_toggle,
    ])

    # Toggle lists
    self._refresh_toggles = (
      ("AdbEnabled", self._adb_toggle),
      ("SshEnabled", self._ssh_toggle),
      ("TailscaleEnabled", self._tailscale_toggle),
      ("AgentEnabled", self._agent_toggle),
      ("JoystickDebugMode", self._joystick_toggle),
      ("LongitudinalManeuverMode", self._long_maneuver_toggle),
      ("LateralManeuverMode", self._lat_maneuver_toggle),
      ("AlphaLongitudinalEnabled", self._alpha_long_toggle),
      ("ShowDebugInfo", self._debug_mode_toggle),
      ("NavigationEnabled", self._navigation_toggle),
    )
    onroad_blocked_toggles = (self._adb_toggle, self._joystick_toggle)
    release_blocked_toggles = (self._joystick_toggle, self._long_maneuver_toggle, self._lat_maneuver_toggle, self._alpha_long_toggle, self._navigation_toggle)
    engaged_blocked_toggles = (self._long_maneuver_toggle, self._lat_maneuver_toggle, self._alpha_long_toggle)

    # Hide non-release toggles on release builds
    for item in release_blocked_toggles:
      item.set_visible(not ui_state.is_release)

    # Disable toggles that require offroad
    for item in onroad_blocked_toggles:
      item.set_enabled(lambda: ui_state.is_offroad())
    # Jetlink holds the USB port that ADB needs
    self._adb_toggle.set_enabled(lambda: ui_state.is_offroad() and not ui_state.adb_blocked)
    # AI agent is parked-only by design (manager offroad gate + MCP gate)
    self._agent_toggle.set_enabled(lambda: ui_state.is_offroad())

    # Disable toggles that require not engaged
    for item in engaged_blocked_toggles:
      item.set_enabled(lambda: not ui_state.engaged)

    # Grey pill: long maneuver is meaningless without longitudinal control, so grey
    # the pill while keeping the stored value so it applies again once the car gains it
    self._long_maneuver_toggle.set_superseded(
        lambda: ui_state.CP is not None and not ui_state.has_longitudinal_control)

    # Set initial state
    if ui_state.params.get_bool("ShowDebugInfo"):
      gui_app.set_show_touches(True)
      gui_app.set_show_fps(True)

    ui_state.add_offroad_transition_callback(self._update_toggles)

  def _update_state(self):
    super()._update_state()
    self._ssh_fetcher.update()

  def show_event(self):
    super().show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    # CP gating
    if ui_state.CP is not None:
      alpha_avail = ui_state.CP.alphaLongitudinalAvailable
      if not alpha_avail or ui_state.is_release:
        self._alpha_long_toggle.set_visible(False)
        ui_state.params.remove("AlphaLongitudinalEnabled")
      else:
        self._alpha_long_toggle.set_visible(True)

      long_man_enabled = ui_state.has_longitudinal_control and ui_state.is_offroad()
      self._long_maneuver_toggle.set_enabled(long_man_enabled)
      self._lat_maneuver_toggle.set_enabled(ui_state.is_offroad())
    else:
      self._long_maneuver_toggle.set_enabled(False)
      self._lat_maneuver_toggle.set_enabled(False)
      self._alpha_long_toggle.set_visible(False)

    # Refresh toggles from params to mirror external changes
    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))
    self._agent_password_btn.set_value(ui_state.params.get("AgentPassword") or tr("Not set"))

  def _on_enable_tailscale(self, state: bool):
    if state:
      # Same dialog as the tici page: polls TailscaleState (written by AGNOS's
      # tailscale-manager) and shows the pairing QR until joined.
      gui_app.push_widget(TailscaleDialog(ui_state.params))

  def _on_show_tailscale_qr(self):
    gui_app.push_widget(TailscaleDialog(ui_state.params))

  def _on_enable_agent(self, state: bool):
    if state:
      # Generate the web login password up front and clear the idle-suspend
      # marker so the manager spawns the agent on the next offroad pass.
      from openpilot.sunnypilot.agent.agent_process import ensure_password
      ensure_password(ui_state.params)
      ui_state.params.remove("AgentSuspended")
      self._agent_password_btn.set_value(ui_state.params.get("AgentPassword") or tr("Not set"))

  def _on_reset_agent_password(self):
    gui_app.push_widget(AgentPasswordConfirmPage(self._do_reset_agent_password))

  def _do_reset_agent_password(self):
    from openpilot.sunnypilot.agent.agent_process import reset_password
    self._agent_password_btn.set_value(reset_password(ui_state.params))

  def _on_set_agent_password(self):
    def set_password(text: str):
      if text:
        ui_state.params.put("AgentPassword", text, block=True)
        self._agent_password_btn.set_value(text)

    dlg = BigInputDialog(
      tr("enter agent password..."),
      ui_state.params.get("AgentPassword") or "",
      minimum_length=4,
      confirm_callback=set_password,
    )
    gui_app.push_widget(dlg)

  def _on_joystick_debug_mode(self, state: bool):
    ui_state.params.put_bool("JoystickDebugMode", state, block=True)
    ui_state.params.put_bool("LongitudinalManeuverMode", False, block=True)
    self._long_maneuver_toggle.set_checked(False)
    ui_state.params.put_bool("LateralManeuverMode", False, block=True)
    self._lat_maneuver_toggle.set_checked(False)

  def _on_long_maneuver_mode(self, state: bool):
    ui_state.params.put_bool("LongitudinalManeuverMode", state, block=True)
    ui_state.params.put_bool("JoystickDebugMode", False, block=True)
    self._joystick_toggle.set_checked(False)
    ui_state.params.put_bool("LateralManeuverMode", False, block=True)
    self._lat_maneuver_toggle.set_checked(False)
    restart_needed_callback()

  def _on_lat_maneuver_mode(self, state: bool):
    ui_state.params.put_bool("LateralManeuverMode", state, block=True)
    ui_state.params.put_bool("JoystickDebugMode", False, block=True)
    self._joystick_toggle.set_checked(False)
    ui_state.params.put_bool("LongitudinalManeuverMode", False, block=True)
    self._long_maneuver_toggle.set_checked(False)
    restart_needed_callback()

  def _on_alpha_long_enabled(self, state: bool):
    def do_toggle(_state: bool):
      ui_state.params.put_bool("AlphaLongitudinalEnabled", _state, block=True)
      restart_needed_callback()
      self._update_toggles()

    if state:
      # Don't show enabled state until confirm
      self._alpha_long_toggle.set_checked(False)
      gui_app.push_widget(AlphaLongConfirmPage(lambda: do_toggle(True)))
    else:
      do_toggle(False)
