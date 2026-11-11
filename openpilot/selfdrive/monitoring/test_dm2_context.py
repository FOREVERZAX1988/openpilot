
from openpilot.selfdrive.monitoring.config import configure_monitoring
from openpilot.selfdrive.monitoring.dm2_context import (AutomaticCancelFilter, CameraAvailability, CancelPressSequence,
                                                       InteractionEdges, ObjectObservation, TrafficContext)
from openpilot.common.test import OpenpilotTestCase, approx
from openpilot.common.parameterized import parameterized


def obj(x=30, y=0, speed=20, relative_speed=0):
  return ObjectObservation(x, y, speed, relative_speed)


def confirm(ctx, start=0, objects=None):
  for i in range(6):
    ctx.update(start + i * .05, [obj()] if objects is None else objects, True, True, True)



class TestDm2ContextTests(OpenpilotTestCase):

  def test_new_vehicle_strict_window_is_not_occupancy_timer(self):
    ctx = TrafficContext()
    for i in range(601):
      now = i / 20
      strict, clear = ctx.update(now, [obj()], True, True, True)
      assert strict == (.2 <= now < 20.2)
      assert not clear
    confirm(ctx, 30.05, [obj(), obj(60, 3)])
    assert ctx.strict_until == approx(20.2)


  def test_new_vehicles_during_hold_do_not_extend_it_and_all_must_leave_to_rearm(self):
    ctx = TrafficContext()
    confirm(ctx)
    confirm(ctx, 1, [obj(), obj(60, 3)])
    assert ctx.strict_until == approx(20.2)
    for i in range(41):
      # Original car leaves, but the adjacent vehicle stays: still occupied.
      ctx.update(2 + i / 20, [obj(60, 3)], True, True, True)
    confirm(ctx, 4.1, [obj(60, 3), obj(90, -3)])
    assert ctx.strict_until == approx(20.2)
    ctx.update(7, [], True, True, True)
    confirm(ctx, 8)
    assert 28.2 <= ctx.strict_until <= 28.25  # Confirmation is sampled at 20 Hz.


  def test_dropout_lane_change_and_duplicate_do_not_restart_timer(self):
    ctx = TrafficContext()
    confirm(ctx)
    ctx.update(1, [], True, True, True)
    ctx.update(1.5, [obj(31, 1), obj(31.2, 1.1)], True, True, True)
    ctx.update(2, [obj(32, 2.5)], True, True, True)
    assert ctx.strict_until == approx(20.2)
    assert len(ctx.tracks) == 1


  def test_genuinely_new_appearance_after_absence_retriggers(self):
    ctx = TrafficContext()
    confirm(ctx)
    ctx.update(3, [], True, True, True)
    confirm(ctx, 4)
    assert ctx.strict_until == approx(24.2)


  def test_same_speed_traffic_counts_but_stationary_and_slow_noise_do_not(self):
    ctx = TrafficContext()
    confirm(ctx, objects=[obj(speed=20, relative_speed=0)])
    assert ctx.strict_until > 20
    ctx = TrafficContext()
    for t in range(20):
      assert ctx.update(t, [obj(speed=0), obj(60, 3, speed=1.9)], True, True, True) == (False, t >= 10)


  def test_single_moving_spike_revokes_clear_but_does_not_start_twenty_second_override(self):
    ctx = TrafficContext()
    ctx.update(0, [], True, True, True)
    assert ctx.update(10, [], True, True, True) == (False, True)
    assert ctx.update(11, [obj()], True, True, True) == (False, False)
    assert ctx.update(11.1, [], True, True, True) == (False, False)
    assert ctx.strict_until == 0


  @parameterized.expand([(False, True, True), (True, False, True), (True, True, False)], names=('healthy', 'straight', 'coverage'))
  def test_unknown_or_curved_road_never_earns_empty_road_bonus(self, healthy, straight, coverage):
    ctx = TrafficContext()
    for t in range(30):
      assert not ctx.update(t, [], healthy, straight, coverage)[1]


  def test_clear_road_requires_continuous_ten_seconds_and_stale_data_revokes_it(self):
    ctx = TrafficContext()
    assert ctx.update(0, [], True, True, True) == (False, False)
    assert ctx.update(10, [], True, True, True) == (False, True)
    assert ctx.update(11, [], False, True, True) == (True, False)
    assert ctx.update(12, [], True, True, True) == (False, False)


  def test_invalid_geometry_is_conservative(self):
    assert TrafficContext().update(0, [obj(x=float('nan'))], True, True, True) == (True, False)


  def test_held_controls_and_repeated_button_packets_are_not_repeated_responses(self):
    edges = InteractionEdges()
    assert edges.update(0, True, False, True, [('accelCruise', True)])
    for t in range(1, 21):
      assert not edges.update(t, True, False, True, [('accelCruise', True)])
    assert edges.last_response == 0
    assert not edges.update(21, False, False, False, [('accelCruise', False)])
    assert edges.update(22, False, True, False, [('accelCruise', True)])
    assert edges.last_response == 22


  def test_supported_buttons_are_responses_and_unknown_buttons_are_not(self):
    edges = InteractionEdges()
    assert edges.update(0, False, False, False, [('gapAdjustCruise', True)])
    assert not edges.update(1, False, False, False, [('unknown', True)])
    assert edges.last_response == 0


  def test_cancel_sequence_accepts_third_press_at_three_second_boundary(self):
    sequence = CancelPressSequence()
    assert not sequence.update(10.0, [('cancel', True)])
    assert not sequence.update(10.1, [('cancel', False)])
    assert not sequence.update(11.5, [('cancel', True)])
    assert not sequence.update(11.6, [('cancel', False)])
    assert sequence.update(13.0, [('cancel', True)])


  def test_cancel_sequence_counts_only_press_edges_rearmed_by_release(self):
    sequence = CancelPressSequence()
    assert not sequence.update(0.0, [('cancel', True)])
    assert not sequence.update(0.5, [('cancel', True)])
    assert not sequence.update(1.0, [('cancel', True)])
    assert not sequence.update(1.1, [('cancel', False)])
    assert not sequence.update(1.5, [('cancel', True)])
    assert not sequence.update(1.6, [('cancel', False)])
    assert sequence.update(2.0, [('cancel', True)])


  def test_cancel_sequence_timeout_restarts_with_latest_press(self):
    sequence = CancelPressSequence()
    assert not sequence.update(0.0, [('cancel', True), ('cancel', False)])
    assert not sequence.update(1.0, [('cancel', True), ('cancel', False)])
    assert not sequence.update(3.01, [('cancel', True), ('cancel', False)])
    assert not sequence.update(4.0, [('cancel', True), ('cancel', False)])
    assert sequence.update(6.0, [('cancel', True)])


  @parameterized.expand([True, False], names=('pressed',))
  def test_cancel_sequence_other_button_event_resets_progress(self, pressed):
    sequence = CancelPressSequence()
    assert not sequence.update(0.0, [('cancel', True), ('cancel', False)])
    assert not sequence.update(0.5, [('cancel', True), ('cancel', False)])
    assert not sequence.update(1.0, [('gapAdjustCruise', pressed)])
    assert not sequence.update(1.5, [('cancel', True), ('cancel', False)])
    assert not sequence.update(2.0, [('cancel', True), ('cancel', False)])
    assert sequence.update(2.5, [('cancel', True)])


  def test_cancel_sequence_invalid_time_resets_and_does_not_seed_progress(self):
    sequence = CancelPressSequence()
    assert not sequence.update(0.0, [('cancel', True), ('cancel', False)])
    assert not sequence.update(0.5, [('cancel', True), ('cancel', False)])
    assert not sequence.update(float('nan'), [])
    assert not sequence.update(float('inf'), [('cancel', True), ('cancel', False)])
    assert not sequence.update(2.0, [('cancel', True), ('cancel', False)])
    assert not sequence.update(2.5, [('cancel', True), ('cancel', False)])
    assert sequence.update(3.0, [('cancel', True)])


  def test_cancel_sequence_stream_reset_rearms_after_a_lost_release(self):
    sequence = CancelPressSequence()
    assert not sequence.update(0.0, [('cancel', True)])
    sequence.reset_input_stream()
    assert not sequence.update(0.5, [('cancel', True), ('cancel', False)])
    assert not sequence.update(1.0, [('cancel', True), ('cancel', False)])
    assert sequence.update(1.5, [('cancel', True)])


  def test_automatic_cancel_filter_rejects_only_post_request_echo_window(self):
    cancel_filter = AutomaticCancelFilter()
    cancel_filter.record(10.0, requested=True)
    cancel_filter.record(10.2, requested=True)
    assert cancel_filter.is_physical(9.99)
    assert not cancel_filter.is_physical(10.1)
    assert not cancel_filter.is_physical(10.3)
    assert cancel_filter.is_physical(10.351)
    cancel_filter.record(float('nan'), requested=True)
    cancel_filter.record(11.0, requested=False)
    assert cancel_filter.is_physical(11.0)


  def test_automatic_cancel_filter_suppresses_echo_press_and_paired_release(self):
    cancel_filter = AutomaticCancelFilter()
    cancel_filter.record(10.0, requested=True)
    assert cancel_filter.filter_buttons(10.1, [('cancel', True), ('gapAdjustCruise', True)]) == [('gapAdjustCruise', True)]
    assert cancel_filter.filter_buttons(10.2, [('cancel', False)]) == []
    assert cancel_filter.filter_buttons(10.351, [('cancel', True), ('cancel', False)]) == [('cancel', True), ('cancel', False)]


  def test_automatic_cancel_release_cannot_rearm_an_interleaved_physical_press(self):
    cancel_filter = AutomaticCancelFilter()
    cancel_filter.record(10.0, requested=True)
    assert cancel_filter.filter_buttons(10.1, [('cancel', True)]) == []
    assert cancel_filter.filter_buttons(10.2, [('cancel', True)]) == [('cancel', True)]
    assert cancel_filter.filter_buttons(10.21, [('cancel', False)]) == []


  def test_automatic_cancel_suppression_resets_after_input_stream_loss(self):
    cancel_filter = AutomaticCancelFilter()
    cancel_filter.record(10.0, requested=True)
    assert cancel_filter.filter_buttons(10.1, [('cancel', True)]) == []
    cancel_filter.reset_input_stream()
    assert cancel_filter.filter_buttons(10.2, [('cancel', True), ('cancel', False)]) == [('cancel', True), ('cancel', False)]


  def test_automatic_cancel_suppression_expires_after_a_lost_release(self):
    cancel_filter = AutomaticCancelFilter()
    cancel_filter.record(10.0, requested=True)
    assert cancel_filter.filter_buttons(10.1, [('cancel', True)]) == []
    assert cancel_filter.filter_buttons(10.7, [('cancel', True), ('cancel', False)]) == [('cancel', True), ('cancel', False)]


class FakeParams:
  def __init__(self, values):
    self.values = dict(values)

  def get(self, name):
    return self.values.get(name)

  def get_int(self, name):
    return int(self.get(name) or 0)

  def get_bool(self, name):
    return self.get_int(name) == 1

  def put(self, name, value):
    expected = {'DriverMonitoringMode': int, 'DisableDM': int, 'CarrotVisionEnabled': bool}[name]
    if type(value) is not expected:
      raise TypeError(f'{name} requires {expected.__name__}, got {type(value).__name__}')
    self.values[name] = value

  def put_int(self, name, value):
    self.put(name, value)

  def put_bool(self, name, value):
    self.put(name, value)


  @parameterized.expand([0, 1, 2], names=('old',))
  def test_legacy_modes_never_migrate_to_experimental(self, old):
    params, env = FakeParams({'DisableDM': old}), {}
    configure_monitoring(params, env)
    assert params.get_int('DriverMonitoringMode') == 0
    assert params.get_bool('CarrotVisionEnabled') == (old == 2)
    assert 'CARROT_DM_MODE' not in env
    params.put_bool('CarrotVisionEnabled', False)
    params.put('DriverMonitoringMode', 1)
    configure_monitoring(params, env)
    assert not params.get_bool('CarrotVisionEnabled')
    assert 'CARROT_DM_MODE' not in env


  @parameterized.expand([None, False, True], names=('existing_video',))
  def test_first_boot_uses_typed_defaults_and_preserves_existing_video(self, existing_video):
    params = FakeParams({} if existing_video is None else {'CarrotVisionEnabled': existing_video})
    env = {}
    configure_monitoring(params, env)
    assert params.get('DriverMonitoringMode') == 0
    assert type(params.get('DriverMonitoringMode')) is int
    assert params.get('CarrotVisionEnabled') is bool(existing_video)
    saved = params.values.copy()
    configure_monitoring(params, env)
    assert params.values == saved and 'CARROT_DM_MODE' not in env


  def test_camera_failure_falls_back_immediately_and_recovery_needs_continuous_health(self):
    camera = CameraAvailability()
    assert not camera.update(0, False)
    assert not camera.update(1, True)
    assert camera.update(3, True)
    assert not camera.update(3.05, False)
    assert not camera.update(4, True)
    assert not camera.update(5, False)
    assert not camera.update(6, True)
    assert not camera.update(7.95, True)
    assert camera.update(8, True)


  @parameterized.expand([-1, 0, 1, 2], names=('saved',))
  def test_live_mode_reads_params_and_ignores_retired_startup_environment(self, monkeypatch, saved):
    from openpilot.selfdrive.monitoring.config import experimental_mode
    monkeypatch.setenv('CARROT_DM_MODE', '0' if saved == 1 else '1')
    params = FakeParams({'DriverMonitoringMode': saved})
    assert experimental_mode(params) == (saved == 1)
    params.put_int('DriverMonitoringMode', 1 if saved != 1 else 0)
    assert experimental_mode(params) == (saved != 1)
