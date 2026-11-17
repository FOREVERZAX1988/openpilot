# Car Porting & Vehicle Adaptation Quick Reference

How openpilot (and this sunnypilot fork) talks to cars, and where each piece
lives in THIS repo.

## Where car code lives

- `opendbc_repo/opendbc/car/<brand>/` - interface.py (CarInterface),
  carstate.py (CAN -> CarState), carcontroller.py (CarControl -> CAN),
  `<brand>can.py` (TX message composition), values.py (actuation limits,
  steering constraints, supported cars), radar_interface.py.
- `opendbc_repo/opendbc/sunnypilot/<brand>/` - SP extension layer
  (`*_ext.py` siblings extend the stock files; stock files stay untouched).
- `opendbc_repo/opendbc/safety/modes/<brand>.h` - panda safety firmware logic
  (C, MISRA). `opendbc_repo/opendbc/safety/tests/test_<brand>.py` - CI tests.
- `openpilot/selfdrive/car/car_specific.py` - brand-specific event logic.
- Fingerprints: `opendbc_repo/opendbc/car/fingerprints.py` (ECU addr lists per
  model). DBC definitions: `opendbc_repo/opendbc/dbc/`.

## Fork extension pattern

sunnypilot extends stock via `*_ext.py` siblings - NEVER duplicate upstream
classes. Car-side: `opendbc/sunnypilot/<brand>/carstate_ext.py`,
`carcontroller_ext.py`. Feature gates are Params (see
`openpilot/common/params_keys.h`), not hardcoded behavior.

## Safety firmware is the hard boundary

Any change under `opendbc_repo/opendbc/safety/` MUST keep the full test suite
passing with 100% coverage:

```bash
cd opendbc_repo/opendbc/safety/tests && bash test.sh
```

Monitored CAN messages lagging >1s cause automatic disengage
(`controls_allowed=false`) - adding new message reads must respect this.

## Port workflow (model port vs brand port)

1. Check supported cars in `opendbc_repo/opendbc/car/<brand>/values.py` and
   `docs/CARS.md`; find the closest already-supported platform.
2. Capture a CAN route from the target car (cabana/replay on PC:
   `tools/op.sh replay`, `tools/op.sh cabana`).
3. Build the fingerprint entry, then carstate/carcontroller/values; safety
   mode in the panda firmware layer if messages need gating.
4. SP-side tweaks go in `opendbc/sunnypilot/<brand>/`.
5. Validate: safety test suite, then `tools/op.sh test opendbc_repo` (if
   configured), then process replay before any onroad testing.

References: `docs/how-to/car-port.md` (structure + example PRs), `docs/CARS.md`
(supported models), `docs/SAFETY.md` and `docs/DEBUGGING_SAFETY.md`.
