from openpilot.common.params import Params
from openpilot.selfdrive.ui.widgets.ssh_key import ssh_key_item
from openpilot.selfdrive.ui.widgets.tailscale_dialog import TailscaleDialog
from openpilot.system.ui.sunnypilot.widgets.input_dialog import InputDialogSP
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.sunnypilot.agent.agent_process import ensure_password, reset_password
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import button_item, dual_button_item, toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult

if gui_app.sunnypilot_ui():
  from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp as toggle_item

# Description constants
DESCRIPTIONS = {
  'enable_adb': tr_noop(
    "ADB (Android Debug Bridge) allows connecting to your device over USB or over the network. " +
    "See https://docs.comma.ai/how-to/connect-to-comma for more info."
  ),
  'ssh_key': tr_noop(
    "Warning: This grants SSH access to all public keys in your GitHub settings. Never enter a GitHub username " +
    "other than your own. A comma employee will NEVER ask you to add their GitHub username."
  ),
  'tailscale': tr_noop(
    "Remote SSH from anywhere via Tailscale. Enable, then scan the QR with the Tailscale app on your phone. " +
    "Works over LTE too. An AGNOS update with tailscaled is required."
  ),
  'ai_agent': tr_noop(
    "Built-in AI agent (opencode). Offroad only; browser access on port 5095; the password is shown in the next row. " +
    "Vehicle-control parameters are hard-blocked. Requires an AGNOS update with opencode."
  ),
  'agent_password': tr_noop(
    "Web login for the AI agent browser page (port 5095): username is always opencode, "
    "the password is shown below. "
    + "Set to type a custom one; Reset to generate a random one. "
    + "The change takes effect within a minute, when the agent restarts."
  ),
  'tailscale_qr': tr_noop(
    "Reopen the Tailscale pairing QR and the SSH address while Remote SSH is enabled."
  ),
  'alpha_longitudinal': tr_noop(
    "<b>WARNING: sunnypilot longitudinal control is in alpha for this car and may disable Automatic Emergency Braking (AEB).</b><br><br>" +
    "On this car, sunnypilot defaults to the car's built-in ACC instead of sunnypilot's longitudinal control. " +
    "Enable this to switch to sunnypilot longitudinal control. " +
    "Enabling Experimental mode is recommended when enabling sunnypilot longitudinal control alpha. " +
    "Changing this setting will restart sunnypilot if the car is powered on."
  ),
}


class DeveloperLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._is_release = False  # self._params.get_bool("IsReleaseBranch")

    # Build items and keep references for callbacks/state updates
    self._adb_toggle = toggle_item(
      lambda: tr("Enable ADB"),
      description=lambda: tr(DESCRIPTIONS["enable_adb"]),
      initial_state=self._params.get_bool("AdbEnabled"),
      callback=self._on_enable_adb,
      # Jetlink holds the USB port that ADB needs
      enabled=lambda: ui_state.is_offroad() and not ui_state.adb_blocked,
    )

    # SSH enable toggle + SSH key management
    self._ssh_toggle = toggle_item(
      lambda: tr("Enable SSH"),
      description="",
      initial_state=self._params.get_bool("SshEnabled"),
      callback=self._on_enable_ssh,
    )
    self._ssh_keys = ssh_key_item(lambda: tr("SSH Keys"), description=lambda: tr(DESCRIPTIONS["ssh_key"]))

    # Remote SSH (Tailscale): AGNOS tailscale-manager joins/leaves on this param
    self._tailscale_toggle = toggle_item(
      lambda: tr("Remote SSH (Tailscale)"),
      description=lambda: tr(DESCRIPTIONS["tailscale"]),
      initial_state=self._params.get_bool("TailscaleEnabled"),
      callback=self._on_enable_tailscale,
    )

    # Reopen the pairing dialog any time (not just on toggle-on): shows the
    # QR while pairing, or the final SSH address once joined.
    self._tailscale_qr = button_item(
      lambda: tr("Pairing QR Code"),
      lambda: tr("Show"),
      description=lambda: tr(DESCRIPTIONS["tailscale_qr"]),
      callback=self._on_show_tailscale_qr,
    )

    # Built-in AI agent (opencode web, port 5095): manager-hosted, offroad only
    self._agent_toggle = toggle_item(
      lambda: tr("AI Agent"),
      description=lambda: self._agent_description(),
      initial_state=self._params.get_bool("AgentEnabled"),
      callback=self._on_enable_agent,
    )

    # Agent password: view (in description) + edit (Set) + regenerate (Reset)
    self._agent_password = dual_button_item(
      lambda: tr("Set"),
      lambda: tr("Reset"),
      left_callback=self._on_set_agent_password,
      right_callback=self._on_reset_agent_password,
      description=lambda: self._agent_password_description(),
    )

    self._joystick_toggle = toggle_item(
      lambda: tr("Joystick Debug Mode"),
      description="",
      initial_state=self._params.get_bool("JoystickDebugMode"),
      callback=self._on_joystick_debug_mode,
      enabled=ui_state.is_offroad,
    )

    self._long_maneuver_toggle = toggle_item(
      lambda: tr("Longitudinal Maneuver Mode"),
      description="",
      initial_state=self._params.get_bool("LongitudinalManeuverMode"),
      callback=self._on_long_maneuver_mode,
    )

    self._lat_maneuver_toggle = toggle_item(
      lambda: tr("Lateral Maneuver Mode"),
      description="",
      initial_state=self._params.get_bool("LateralManeuverMode"),
      callback=self._on_lat_maneuver_mode,
    )

    self._alpha_long_toggle = toggle_item(
      lambda: tr("sunnypilot Longitudinal Control (Alpha)"),
      description=lambda: tr(DESCRIPTIONS["alpha_longitudinal"]),
      initial_state=self._params.get_bool("AlphaLongitudinalEnabled"),
      callback=self._on_alpha_long_enabled,
      enabled=lambda: not ui_state.engaged,
    )

    self._ui_debug_toggle = toggle_item(
      lambda: tr("UI Debug Mode"),
      description="",
      initial_state=self._params.get_bool("ShowDebugInfo"),
      callback=self._on_enable_ui_debug,
    )
    self._on_enable_ui_debug(self._params.get_bool("ShowDebugInfo"))

    self._scroller = Scroller([
      self._adb_toggle,
      self._ssh_toggle,
      self._ssh_keys,
      self._tailscale_toggle,
      self._tailscale_qr,
      self._agent_toggle,
      self._agent_password,
      self._joystick_toggle,
      self._long_maneuver_toggle,
      self._lat_maneuver_toggle,
      self._alpha_long_toggle,
      self._ui_debug_toggle,
    ], line_separator=True, spacing=0)

    # Toggles should be not available to change in onroad state
    ui_state.add_offroad_transition_callback(self._update_toggles)

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    # Hide non-release toggles on release builds
    # TODO: we can do an onroad cycle, but alpha long toggle requires a deinit function to re-enable radar and not fault
    for item in (self._joystick_toggle, self._long_maneuver_toggle, self._lat_maneuver_toggle, self._alpha_long_toggle):
      item.set_visible(not self._is_release)

    # CP gating
    if ui_state.CP is not None:
      alpha_avail = ui_state.CP.alphaLongitudinalAvailable
      if not alpha_avail or self._is_release:
        self._alpha_long_toggle.set_visible(False)
        self._params.remove("AlphaLongitudinalEnabled")
      else:
        self._alpha_long_toggle.set_visible(True)

      long_man_enabled = ui_state.has_longitudinal_control and ui_state.is_offroad()
      self._long_maneuver_toggle.action_item.set_enabled(long_man_enabled)
      self._lat_maneuver_toggle.action_item.set_enabled(ui_state.is_offroad())
    else:
      self._long_maneuver_toggle.action_item.set_enabled(False)
      self._lat_maneuver_toggle.action_item.set_enabled(False)
      self._alpha_long_toggle.set_visible(False)

    # TODO: make a param control list item so we don't need to manage internal state as much here
    # refresh toggles from params to mirror external changes
    for key, item in (
      ("AdbEnabled", self._adb_toggle),
      ("SshEnabled", self._ssh_toggle),
      ("TailscaleEnabled", self._tailscale_toggle),
      ("AgentEnabled", self._agent_toggle),
      ("JoystickDebugMode", self._joystick_toggle),
      ("LongitudinalManeuverMode", self._long_maneuver_toggle),
      ("LateralManeuverMode", self._lat_maneuver_toggle),
      ("AlphaLongitudinalEnabled", self._alpha_long_toggle),
      ("ShowDebugInfo", self._ui_debug_toggle),
    ):
      item.action_item.set_state(self._params.get_bool(key))

  def _on_enable_ui_debug(self, state: bool):
    self._params.put_bool("ShowDebugInfo", state, block=True)
    gui_app.set_show_touches(state)
    gui_app.set_show_fps(state)
    gui_app.set_show_mouse_coords(state)

  def _on_enable_adb(self, state: bool):
    self._params.put_bool("AdbEnabled", state, block=True)

  def _on_enable_ssh(self, state: bool):
    self._params.put_bool("SshEnabled", state, block=True)

  def _on_show_tailscale_qr(self):
    gui_app.push_widget(TailscaleDialog(self._params))

  def _on_enable_tailscale(self, state: bool):
    self._params.put_bool("TailscaleEnabled", state, block=True)
    if state:
      # tailscale-manager reacts within ~5s; the dialog polls TailscaleState
      # and shows the pairing QR / final SSH address.
      gui_app.push_widget(TailscaleDialog(self._params))

  def _agent_description(self) -> str:
    description = tr(DESCRIPTIONS["ai_agent"])
    address = self._params.get("NetworkAddress") or "<device-ip>"
    return f"{description}\nhttp://{address}:5095"

  def _agent_password_description(self) -> str:
    header = tr(DESCRIPTIONS["agent_password"])
    password = self._params.get("AgentPassword")
    if password:
      return header + "\n" + f"{tr('Current password')}: {password}"
    return header + "\n" + tr("No password generated yet — toggle AI Agent on to create one")

  def _on_set_agent_password(self):
    dlg = InputDialogSP(
      tr("Set agent password"),
      sub_title=tr("Used to log in to the agent web page on port 5095"),
      current_text=self._params.get("AgentPassword") or "",
      param="AgentPassword",
    )
    dlg.show()

  def _on_enable_agent(self, state: bool):
    if state:
      # Generate the web login password up front so the UI can display it,
      # and clear the idle-suspend marker so the manager spawns it now.
      ensure_password(self._params)
      self._params.remove("AgentSuspended")
    self._params.put_bool("AgentEnabled", state, block=True)

  def _on_reset_agent_password(self):
    reset_password(self._params)  # dual button's description lambda re-renders with the new value

  def _on_joystick_debug_mode(self, state: bool):
    self._params.put_bool("JoystickDebugMode", state, block=True)
    self._params.put_bool("LongitudinalManeuverMode", False, block=True)
    self._long_maneuver_toggle.action_item.set_state(False)
    self._params.put_bool("LateralManeuverMode", False, block=True)
    self._lat_maneuver_toggle.action_item.set_state(False)

  def _on_long_maneuver_mode(self, state: bool):
    self._params.put_bool("LongitudinalManeuverMode", state, block=True)
    self._params.put_bool("JoystickDebugMode", False, block=True)
    self._joystick_toggle.action_item.set_state(False)
    self._params.put_bool("LateralManeuverMode", False, block=True)
    self._lat_maneuver_toggle.action_item.set_state(False)

  def _on_lat_maneuver_mode(self, state: bool):
    self._params.put_bool("LateralManeuverMode", state, block=True)
    self._params.put_bool("JoystickDebugMode", False, block=True)
    self._joystick_toggle.action_item.set_state(False)
    self._params.put_bool("LongitudinalManeuverMode", False, block=True)
    self._long_maneuver_toggle.action_item.set_state(False)

  def _on_alpha_long_enabled(self, state: bool):
    if state:
      def confirm_callback(result: DialogResult):
        if result == DialogResult.CONFIRM:
          self._params.put_bool("AlphaLongitudinalEnabled", True, block=True)
          self._params.put_bool("OnroadCycleRequested", True, block=True)
          self._update_toggles()
        else:
          self._alpha_long_toggle.action_item.set_state(False)

      # show confirmation dialog
      content = (f"<h1>{self._alpha_long_toggle.title}</h1><br>" +
                 f"<p>{self._alpha_long_toggle.description}</p>")

      dlg = ConfirmDialog(content, tr("Enable"), rich=True, callback=confirm_callback)
      gui_app.push_widget(dlg)

    else:
      self._params.put_bool("AlphaLongitudinalEnabled", False, block=True)
      self._params.put_bool("OnroadCycleRequested", True, block=True)
      self._update_toggles()
