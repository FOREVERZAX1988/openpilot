"""Unittest port of the StarPilot FLM adaptive-profile tests.

Verbatim port of starpilot/flm/tests/test_adaptive_profile.py, converted
from pytest to unittest because this fork removed pytest (upstream
98e7c4f987) and ships tools/test_runner.py as the test runner. The frozen
assertions and numeric expectations are unchanged; only the harness form
differs (pytest.mark.parametrize -> unittest subTest).
"""

from dataclasses import replace
import unittest

from openpilot.sunnypilot.flm.adaptive_profile import Block, Parameter, ProfileOwner, ReplayValidation, CurrentAdmission, readmit_profile, Sample, evaluate

IDENTITY = 'a' * 64
PARAMETERS = (Parameter('ff_gain', 'stage1', -.03, .03, .03, .005),)


def blocks():
  result = []
  for index in range(8):
    rows = tuple(Sample(1_000_000_000 + (index * 40 + j) * 10_000_000,
                        990_000_000 + (index * 40 + j) * 10_000_000,
                        995_000_000 + (index * 40 + j) * 10_000_000,
                        (1. + j / 40,), .02 * (1. + j / 40), 1.) for j in range(40))
    result.append(Block(IDENTITY, str(index), 'left' if index % 2 else 'right', 'stage1', 'plant1', rows))
  return tuple(result)


def fit(data=None, parameters=PARAMETERS, **kwargs):
  return evaluate(IDENTITY, parameters, blocks() if data is None else data, now_ns=5_000_000_000,
                  required_cohorts=('left', 'right'), response_revision='plant1', **kwargs)


class TestAdaptiveProfile(unittest.TestCase):
  def test_identified_plant_and_original_expiry(self):
    profile = fit().profile
    self.assertIsNotNone(profile)
    self.assertTrue(0 < profile.coefficients[0] < .02)
    self.assertTrue(profile.candidate_loss < profile.baseline_loss)
    self.assertEqual(profile.expires_ns, profile.observed_ns + 500_000_000)
    self.assertTrue(set(profile.train_ids).isdisjoint(profile.heldout_ids))

  def test_ineligible_response_never_trains(self):
    for field in ['override', 'fault', 'saturated', 'model_wobble', 'controller_chatter']:
      with self.subTest(field=field):
        data = list(blocks())
        rows = list(data[0].samples)
        rows[0] = replace(rows[0], **{field: True})
        data[0] = replace(data[0], samples=tuple(rows))
        self.assertEqual(fit(tuple(data)).reason, 'evidence')

  def test_wrong_physical_model_and_missing_cohort(self):
    data = tuple(replace(block, response_revision='unqualified') for block in blocks())
    self.assertEqual(fit(data).reason, 'provenance')
    data = tuple(replace(block, cohort='left') for block in blocks())
    self.assertEqual(fit(data).reason, 'independent_cohorts')

  def test_heldout_regression_rejected(self):
    data = list(blocks())
    for index in range(4, 8):
      data[index] = replace(data[index], samples=tuple(replace(row, residual_target=-row.residual_target) for row in data[index].samples))
    self.assertEqual(fit(tuple(data)).status, 'rejected')

  def test_confounded_basis_rejected(self):
    for epsilon in [0., 1e-9]:
      with self.subTest(epsilon=epsilon):
        parameters = PARAMETERS + (replace(PARAMETERS[0], name='friction'),)
        data = tuple(replace(block, samples=tuple(replace(row, features=(row.features[0], row.features[0] + epsilon))
                                                for row in block.samples)) for block in blocks())
        self.assertEqual(fit(data, parameters).reason, 'confounded_stage')

  def test_gradual_adoption_same_sequence_mutation_and_exact_fallback(self):
    profile = fit().profile
    self.assertIsNotNone(profile)
    owner = ProfileOwner(IDENTITY, PARAMETERS, baseline_revision="baseline1", physical_model_revision="plant1")
    kwargs = {"active": True, "enabled": True, "manual": False, "healthy": True,
              "replay_validation": ReplayValidation(profile, "baseline1", "plant1", True, True, .001)}
    first = owner.tick(profile, now_ns=5_000_000_000, **kwargs)
    self.assertEqual(first, (.00005,))
    changed = replace(profile, coefficients=(.01,))
    changed_validation = replace(kwargs["replay_validation"], profile=changed)
    self.assertEqual(owner.tick(changed, now_ns=5_010_000_000, **(kwargs | {"replay_validation": changed_validation})), (0.,))
    self.assertEqual(owner.tick(profile, now_ns=5_020_000_000, **kwargs), (.00005,))
    self.assertEqual(owner.tick(profile, now_ns=5_030_000_000, **(kwargs | {'manual': True})), (0.,))
    self.assertEqual(owner.tick(profile, now_ns=5_040_000_000, **(kwargs | {'active': False})), (0.,))
    self.assertEqual(owner.tick(profile, now_ns=5_550_000_001, **kwargs), (0.,))

  def test_live_revalidation_adopts_for_six_seconds_then_stale_withdraws(self):
    fit_profile = fit().profile
    self.assertIsNotNone(fit_profile)
    validation = ReplayValidation(fit_profile, 'baseline', 'physical', True, True, .001)
    owner = ProfileOwner(IDENTITY, PARAMETERS, baseline_revision="baseline", physical_model_revision="physical")
    profile, replay = fit_profile, validation
    for tick in range(601):
      now = 5_000_000_000 + tick * 10_000_000
      if tick % 25 == 0:
        admission = CurrentAdmission(IDENTITY, 'baseline', 'physical', now, True, True, False, True)
        renewed = readmit_profile(fit_profile, validation, admission, now_ns=now, sequence=tick + 2)
        self.assertIsNotNone(renewed)
        profile, replay = renewed
      value = owner.tick(profile, now_ns=now, active=True, enabled=True, manual=False, healthy=True, replay_validation=replay)
    self.assertEqual(value, profile.coefficients)
    stale = replace(admission, source_ns=now - 100_000_001)
    self.assertIsNone(readmit_profile(fit_profile, validation, stale, now_ns=now, sequence=1000))
    self.assertEqual(fit_profile.expires_ns, 5_500_000_000)
    owner.last_ns = profile.expires_ns - 1
    self.assertEqual(owner.tick(profile, now_ns=profile.expires_ns + 1, active=True, enabled=True, manual=False,
                                healthy=True, replay_validation=replay), (0.,))

  def test_owner_rejects_wrong_current_revision(self):
    for field in ['baseline_revision', 'physical_model_revision']:
      with self.subTest(field=field):
        profile = fit().profile
        self.assertIsNotNone(profile)
        owner = ProfileOwner(IDENTITY, PARAMETERS, baseline_revision='baseline', physical_model_revision='physical')
        validation = ReplayValidation(profile, 'baseline', 'physical', True, True, .001)
        self.assertEqual(owner.tick(profile, now_ns=5_000_000_000, active=True, enabled=True, manual=False,
                                    healthy=True, replay_validation=replace(validation, **{field: 'different'})), (0.,))

  def test_historical_prior_regularizes_only_fresh_fit(self):
    neutral = fit().profile
    informed = fit(prior=(.02,)).profile
    self.assertIsNotNone(neutral)
    self.assertIsNotNone(informed)
    self.assertTrue(abs(informed.coefficients[0] - .02) < abs(neutral.coefficients[0] - .02))
    self.assertEqual(informed.train_ids, neutral.train_ids)
    self.assertEqual(informed.heldout_ids, neutral.heldout_ids)
    self.assertIsNone(fit((), prior=(.02,)).profile)
    self.assertEqual(fit(prior=None), fit())

  def test_bad_historical_prior_cannot_admit(self):
    for prior in [(.04,), (float('nan'),), (), [0.], (True,)]:
      with self.subTest(prior=prior):
        self.assertEqual(fit(prior=prior).reason, 'historical_prior')

  def test_prior_cannot_bypass_fresh_override_or_heldout_regression(self):
    data = list(blocks())
    data[0] = replace(data[0], samples=tuple(replace(row, override=True) for row in data[0].samples))
    self.assertEqual(fit(tuple(data), prior=(.02,)).reason, 'evidence')
    data = list(blocks())
    for index in range(4, 8):
      data[index] = replace(data[index], samples=tuple(replace(row, residual_target=-row.residual_target) for row in data[index].samples))
    self.assertEqual(fit(tuple(data), prior=(.02,)).status, 'rejected')


if __name__ == "__main__":
  unittest.main()
