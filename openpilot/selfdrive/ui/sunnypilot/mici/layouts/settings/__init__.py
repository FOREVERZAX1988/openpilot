"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The SP mici settings panel modules (navigation, osm, storage, bluetooth, vehicle,
carrot, ...) live in this package; the registration entry is the settings
submodule. The re-export keeps ``from ...layouts.settings import SettingsLayoutSP``
(main.py, tests) working.
"""
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings.settings import SettingsLayoutSP, SunnylinkBigButton
