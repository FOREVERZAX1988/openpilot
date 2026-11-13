"""Ported from StarPilot flm/tests/test_physical_response.py (pytest -> unittest)."""

import unittest
from dataclasses import replace

from openpilot.sunnypilot.flm.physical_response import PhysicalRow, fit_physical


def rows():
  return tuple(PhysicalRow(str(block), 1_000_000_000 + (block * 40 + index) * 50_000_000,
                           1_110_000_000 + (block * 40 + index) * 50_000_000,
                           (-1 if block % 2 else 1) * (.1 + index * .005),
                           2 * (-1 if block % 2 else 1) * (.1 + index * .005) + .01,
                           'stable_vm_roll_lag', 'right' if block % 2 else 'left', True, False, False)
               for block in range(8) for index in range(40))


def fit(data=None, **kwargs):
  return fit_physical('a' * 64, 'normalized_torque', 'stable_vm_roll_lag', rows() if data is None else data,
                      lag_ns=100_000_000, min_excitation=.05, max_rmse=.001, now_ns=18_000_000_000, **kwargs)


class TestPhysicalResponse(unittest.TestCase):

  def test_physical_plant_separate_heldout_and_no_extrapolation(self):
    model = fit()
    self.assertIsNotNone(model)
    self.assertAlmostEqual(model.slope, 2.)
    self.assertAlmostEqual(model.intercept, .01)
    self.assertFalse(set(model.train_blocks) & set(model.heldout_blocks))
    self.assertAlmostEqual(model.inverse(.41), .2)
    self.assertIsNone(model.inverse(100.))

  def test_invalid_actual_source_rejected(self):
    for mutation in ({'healthy': False}, {'overridden': True}, {'saturated': True},
                     {'context': 'new_vm'}, {'response_ns': 1}, {'command': float('nan')}):
      with self.subTest(mutation=mutation):
        data = list(rows())
        data[0] = replace(data[0], **mutation)
        self.assertIsNone(fit(tuple(data)))

  def test_join_retains_actual_timestamp_and_bounds_hold_age(self):
    data = rows()
    self.assertIsNotNone(fit(tuple(replace(row, response_ns=row.command_ns + 130_000_000) for row in data)))
    self.assertIsNone(fit(tuple(replace(row, response_ns=row.command_ns + 130_000_001) for row in data)))
    self.assertIsNone(fit(tuple(replace(row, response_ns=row.command_ns + 99_999_999) for row in data)))

  def test_train_maturity_and_direction_required(self):
    data = tuple(row for index, row in enumerate(rows()) if index != 0)
    self.assertIsNone(fit(data))
    self.assertIsNone(fit(tuple(replace(row, direction='left') for row in rows())))

  def test_noise_confounding_and_unobserved_range_rejected(self):
    data = rows()
    self.assertIsNone(fit(tuple(replace(row, command=.1) for row in data)))
    self.assertIsNone(fit(tuple(replace(row, physical_response=-row.physical_response) for row in data)))
    self.assertIsNone(fit(tuple(replace(row, physical_response=row.physical_response + (.1 if row.block_id == '7' else 0)) for row in data)))
    self.assertIsNone(fit(tuple(replace(row, command=10.) if row.block_id == '7' else row for row in data)))

  def test_history_is_bounded_without_rejecting_mature_training(self):
    self.assertIsNotNone(fit())
    self.assertIsNone(fit(history_ns=1_000_000_000))
    self.assertIsNone(fit(history_ns=600_000_000_001))
    self.assertIsNone(fit(tuple(replace(row, response_ns=18_000_000_001) for row in rows())))

  def test_block_upper_bound(self):
    data = rows()
    first = tuple(replace(data[0], command_ns=1_000_000_000 + index * 1_000_000,
                          response_ns=1_110_000_000 + index * 1_000_000) for index in range(241))
    self.assertIsNone(fit(first + tuple(row for row in data if row.block_id != '0')))


if __name__ == '__main__':
  unittest.main()
