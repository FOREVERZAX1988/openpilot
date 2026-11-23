"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import os
from pathlib import Path

from openpilot.common.hardware import PC
from openpilot.common.hardware.hw import Paths
from openpilot.selfdrive.ui.mici.layouts.settings.developer import DeveloperLayoutMici
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr

PREBUILT_PATH = os.path.join(Paths.comma_home(), "prebuilt") if PC else "/data/openpilot/prebuilt"


class DeveloperLayoutMiciSP(DeveloperLayoutMici):
  def __init__(self):
    super().__init__()
    # Jetlink holds the USB port that ADB needs
    self._adb_toggle.set_enabled(lambda: ui_state.is_offroad() and not ui_state.adb_blocked)
    # the alpha switch lives in the alpha longitudinal panel
    self._scroller.items.remove(self._alpha_long_toggle)

    self._show_advanced_toggle = BigParamControl(tr("show advanced controls"), "ShowAdvancedControls",
                                                 description=tr("Toggles the visibility of advanced zoompilot controls.\n" +
                                                                "It only changes which toggles are shown, not whether they are enabled."))
    self._github_runner_toggle = BigParamControl(tr("github runner service"), "EnableGithubRunner",
                                                 description=tr("Enables or disables the GitHub runner service."))
    self._copyparty_toggle = BigParamControl(tr("copyparty service"), "EnableCopyparty",
                                             description=tr("copyparty is a file server: download your routes, view your logs and edit files " +
                                                            "from a browser.\n" +
                                                            "Connect to your comma locally via its IP address."))
    self._quickboot_toggle = BigParamControl(tr("quickboot mode"), "QuickBootToggle", toggle_callback=self._on_quickboot_toggled,
                                             description=tr("When toggled on, this creates a prebuilt file to allow accelerated boot times.\n" +
                                                            "When toggled off, it removes the prebuilt file so compilation of " +
                                                            "locally edited cpp files can be made."))

    # insert the advanced group before the debug toggles at the end
    advanced = [self._show_advanced_toggle, self._github_runner_toggle, self._copyparty_toggle, self._quickboot_toggle]
    items = self._scroller.items
    for i, item in enumerate(advanced):
      items.insert(items.index(self._debug_mode_toggle) + i, item)

    self._refresh_toggles = self._refresh_toggles + (
      ("ShowAdvancedControls", self._show_advanced_toggle),
      ("EnableGithubRunner", self._github_runner_toggle),
      ("EnableCopyparty", self._copyparty_toggle),
      ("QuickBootToggle", self._quickboot_toggle),
    )

    self._is_release_branch = ui_state.is_release or ui_state.params.get_bool("IsReleaseSpBranch")
    self._is_development_branch = ui_state.params.get_bool("IsTestedBranch") or ui_state.params.get_bool("IsDevelopmentBranch")

    # mirror the prebuilt file in case it changed outside this panel
    if (prebuilt_file := os.path.exists(PREBUILT_PATH)) != ui_state.params.get_bool("QuickBootToggle"):
      ui_state.params.put_bool("QuickBootToggle", prebuilt_file)
      self._quickboot_toggle.set_checked(prebuilt_file)

    self._update_advanced_visibility()

  @staticmethod
  def _on_quickboot_toggled(state: bool):
    if state:
      Path(PREBUILT_PATH).touch(exist_ok=True)
    else:
      os.remove(PREBUILT_PATH)
    ui_state.params.put_bool("QuickBootToggle", state)

  def _update_advanced_visibility(self):
    show_advanced = ui_state.params.get_bool("ShowAdvancedControls")
    self._copyparty_toggle.set_visible(show_advanced)
    self._github_runner_toggle.set_visible(show_advanced and not self._is_release_branch)
    self._quickboot_toggle.set_visible(show_advanced and not (self._is_release_branch or self._is_development_branch))
    # quickboot needs the package manager out of the way
    self._quickboot_toggle.set_enabled(ui_state.params.get_bool("DisableUpdates"))

  def _update_toggles(self):
    super()._update_toggles()
    self._update_advanced_visibility()
