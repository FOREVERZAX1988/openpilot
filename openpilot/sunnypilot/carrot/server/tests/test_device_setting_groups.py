from openpilot.sunnypilot.carrot.server.services import device_info


def test_defaults_are_derived_from_the_groups_not_restated():
  from_groups = {name: default for _group, entries in device_info.DEVICE_SETTING_GROUPS for name, default in entries}
  assert device_info.DEVICE_SETTING_DEFAULTS == from_groups


def test_no_parameter_appears_in_two_groups():
  names = [name for _group, entries in device_info.DEVICE_SETTING_GROUPS for name, _default in entries]
  assert len(names) == len(set(names))


def _base_owner_by_name() -> dict[str, str]:
  return {
    name: group
    for group, entries in device_info.DEVICE_SETTING_GROUPS
    for name, _default in entries
  }


def test_every_base_default_is_unique_within_the_base_groups():
  grouped = device_info.get_device_setting_group_names()
  # The base groups own their names, so each one is drawn by exactly one group.
  base_names = [name for _group, entries in device_info.DEVICE_SETTING_GROUPS for name, _default in entries]
  assert len(base_names) == len(set(base_names))
  flattened = [name for names in grouped.values() for name in names]
  assert set(device_info.DEVICE_SETTING_DEFAULTS) <= set(flattened)


def test_no_parameter_appears_in_two_device_groups():
  grouped = device_info.get_device_setting_group_names()
  # One param, one row: the merged table (base groups first, then the catalog
  # sections) must never name the same param twice.
  flattened = [name for names in grouped.values() for name in names]
  assert len(flattened) == len(set(flattened))


def test_a_section_never_restates_a_base_param():
  grouped = device_info.get_device_setting_group_names()
  # A sunnypilot section repeats a param only if the catalog menu lists it under
  # a second node; the base groups are the first sections, so a section that
  # restates one of their names would render a duplicate row further down.
  base_owner = _base_owner_by_name()
  for group_id, names in grouped.items():
    for name in names:
      if name in base_owner:
        assert group_id == base_owner[name], f"{name} is on {group_id} and on {base_owner[name]}"


def test_the_group_mapping_keeps_declaration_order():
  grouped = device_info.get_device_setting_group_names()
  base_groups = [group for group, _entries in device_info.DEVICE_SETTING_GROUPS]
  assert list(grouped)[:len(base_groups)] == base_groups
  assert grouped["Device"][0] == "DeviceType"
  assert grouped["Toggles"][0] == "OpenpilotEnabledToggle"


def test_the_base_groups_the_web_renders_are_all_present():
  grouped = device_info.get_device_setting_group_names()
  # Network is read-only and has no parameters, so it is intentionally absent.
  assert {"Device", "Software", "Toggles", "Developer"} <= set(grouped)


def test_sunnypilot_sections_follow_the_catalog_menu():
  grouped = device_info.get_device_setting_group_names()
  sp = device_info._sp_device_setting_groups()
  expected = {gid for gid, names in sp.items() if names}
  assert expected <= set(grouped)
  # sidebar order matches SP_DEVICE_MENU_GROUPS and every name is a string
  order = [gid for gid, _menu in device_info.SP_DEVICE_MENU_GROUPS if gid in grouped]
  assert order == [gid for gid, _menu in device_info.SP_DEVICE_MENU_GROUPS if gid in expected]
  for names in sp.values():
    assert all(isinstance(name, str) and name for name in names)


def test_sunnypilot_sections_have_no_duplicates_within_a_group():
  grouped = device_info.get_device_setting_group_names()
  for group_id, _menu_id in device_info.SP_DEVICE_MENU_GROUPS:
    names = grouped.get(group_id, [])
    # A param may surface in two sections (OsmMapDataEnabled on the osm page
    # and under Maps); a single section must never repeat itself.
    assert len(names) == len(set(names)), f"{group_id} repeats a parameter"


def test_sunnypilot_sections_degrade_to_empty_without_a_catalog(monkeypatch, tmp_path):
  from openpilot.sunnypilot.carrot.server import config
  monkeypatch.setattr(config, "DEFAULT_SETTINGS_PATH", str(tmp_path / "missing.json"))
  monkeypatch.setattr(device_info, "_sp_device_groups_cache", None)
  try:
    assert device_info._sp_device_setting_groups() == {}
  finally:
    monkeypatch.setattr(device_info, "_sp_device_groups_cache", None)


def test_parameters_the_ui_depends_on_are_not_dropped():
  grouped = device_info.get_device_setting_group_names()
  # Each of these drives a specific control; losing one silently blanks it.
  assert "LongitudinalPersonality" in grouped["Toggles"]
  assert "ExperimentalModeConfirmed" in grouped["Toggles"]
  assert "SoftwareMenu" in grouped["Device"]
  assert {"GithubUsername", "GithubSshKeys"} <= set(grouped["Developer"])


def test_the_mapping_is_a_copy_callers_cannot_corrupt():
  first = device_info.get_device_setting_group_names()
  first["Device"].append("Injected")
  assert "Injected" not in device_info.get_device_setting_group_names()["Device"]
