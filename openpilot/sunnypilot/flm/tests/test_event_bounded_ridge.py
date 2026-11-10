"""Bounded train proposal solver tests (pure bounded_ridge subset).

Ported verbatim from StarPilot starpilot/flm/tests/test_event_bounded_ridge.py,
restricted to the box-solver contract tests. The tests that drive
flm.event_evaluate.evaluate_event and flm.tests.test_event_native_backtrack
(event proposal plumbing, native feasibility callbacks) exercise the live
event-wiring layer and return with the controller wiring batch, after
controls-safety review.

Converted from pytest to unittest: this fork removed pytest (upstream
98e7c4f987) and ships tools/test_runner.py as the test runner.
"""
import unittest

from openpilot.sunnypilot.flm.adaptive_profile import Parameter
from openpilot.sunnypilot.flm.event_bounded_ridge import bounded_ridge


def parameter(low=-1., high=1., max_step=1.):
  return Parameter('test', 'test', low, high, max_step, .005)


class TestEventBoundedRidge(unittest.TestCase):
  def test_box_solver_reoptimizes_coupled_free_coordinate_and_satisfies_kkt(self):
    matrix, rhs = ((2., 1.), (1., 2.)), (2., 0.)
    result = bounded_ridge(matrix, rhs, (parameter(), parameter()), (0., 0.), .5)
    self.assertEqual(result, (.5, -.25))
    gradient = tuple(sum(a*b for a, b in zip(row, result, strict=True))-r for row, r in zip(matrix, rhs, strict=True))
    self.assertTrue(gradient[0] < 0 and gradient[1] == 0)  # Upper active / free KKT.
    self.assertNotEqual(result, (.5, -.5))  # Componentwise clamp of unconstrained (4/3,-2/3).

  def test_actual_domain_max_step_and_nonzero_prior_intersection(self):
    for sign in (-1., 1.):
      with self.subTest(sign=sign):
        p = parameter(-.02, .02, .012)
        result = bounded_ridge(((1.,),), (100.*sign,), (p,), (.01*sign,), .005)
        self.assertEqual(result, (.012*sign,))
        self.assertTrue(abs(result[0]-.01*sign) <= .005 and abs(result[0]) <= p.max_step)
        p = parameter(0., .003, .25)
        self.assertEqual(bounded_ridge(((1.,),), (100.,), (p,), (0.,), .005), (.003,))

  def test_nonfinite_and_boolean_solver_inputs_fail_closed(self):
    for matrix, rhs, centre, step in (
      (((float('nan'),),), (1.,), (0.,), .005),
      (((1.,),), (float('inf'),), (0.,), .005),
      (((1.,),), (1.,), (True,), .005),
      (((1.,),), (1.,), (0.,), True),
      (((1.,),), (1.,), (0.,), -.005),
    ):
      with self.subTest(matrix=matrix, rhs=rhs, centre=centre, step=step):
        with self.assertRaises(ValueError):
          bounded_ridge(matrix, rhs, (parameter(),), centre, step)

  def test_all_four_dimensions_and_fixed_training_only_bounded_domain(self):
    matrix = tuple(tuple(2. if i == j else 0. for j in range(4)) for i in range(4))
    self.assertEqual(bounded_ridge(matrix, (10., -10., .002, -.002), (parameter(),)*4, (0.,)*4, .005), (.005, -.005, .001, -.001))


if __name__ == "__main__":
  unittest.main()
