# Tuning & Driving-Feel Quick Reference (sunnypilot)

What controls the driving feel, which files own it, and what you (the agent)
may and may not touch.

## The boundary first

Vehicle-control params are hard-blacklisted for agent writes
(sunnypilot/agent/comma_mcp.py): LongitudinalTuning*, LateralTuning*,
TurnLatControl*, LongitudinalPersonality, Personality*, MADS*, CustomAcc*,
DynamicExperimentalControl, AlphaLongitudinal, CurvatureLateralCtrl,
ExperimentalMode*, OpenpilotEnabledToggle. Explaining tuning options is fine;
writing control params or control-law code needs the owner's hands-on decision
and validation - control changes without replay/track validation are how cars
misbehave onroad.

## Lateral (steering)

- Stock lateral control: model-curvature-driven; lateral MPC was removed
  upstream (direct model curvature output instead).
- Torque-based control: `EnforceTorqueControl` param; implementation in
  `openpilot/selfdrive/locationd/torqued.py` + SP extension
  `openpilot/sunnypilot/selfdrive/locationd/torqued_ext.py`.
- NNLC (Neural Network Lateral Control): `NeuralNetworkLateralControl` param;
  training data is the `openpilot/sunnypilot/neural_network_data/` SUBMODULE
  (never edit it in-tree).
- Live steering latency: `openpilot/sunnypilot/livedelay/`, gated by
  `LagdToggle`.
- Feel knobs: `LaneTurnDesire`, `BlinkerPauseLateralControl`,
  `AutoLaneChangeTimer` params.

## Longitudinal (speed)

- Personality / DEC: `LongitudinalPersonality`, `DynamicExperimentalControl`
  (DEC), `ExperimentalMode` - all control-chain, agent-blacklisted.
- Custom ACC: `CustomAcc` family; SCC smoothing in
  `openpilot/sunnypilot/selfdrive/controls/lib/` .
- Speed limits: `SpeedLimitMode` + mapd (`openpilot/sunnypilot/mapd/`, OSM
  data incl. China provinces).

## MADS (engagement)

Modular Assistive Driving System in `openpilot/sunnypilot/mads/` - custom
engagement/latch logic. Params: `Mads`, `MadsMainCruiseAllowed`,
`MadsUnifiedEngagementMode`, ICBM via `IntelligentCruiseButtonManagement`.
Cereal contract: `SelfdriveStateSP` in `openpilot/cereal/custom.capnp`
(identifier is reserved - NEVER change Cap'n Proto identifiers/field IDs).

## Model runner

Two model runners coexist: stock `openpilot/selfdrive/modeld/` (SNPE) and
`openpilot/sunnypilot/modeld_v2/` (tinygrad), switched by the
`ModelManagerSP.Runner` enum; model bundles managed by `models_manager`
(offroad only).

## Validation discipline

Any change to control behavior: PC replay first
(`openpilot/selfdrive/test/process_replay/test_processes.py`), then owner
drives with `ShowDebugInfo` on. No blind onroad control changes - the agent
never claims a tuning change is "safe to run" without replay evidence.
