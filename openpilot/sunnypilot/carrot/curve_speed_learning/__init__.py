"""
Copyright (c) 2026-, sunnypilot and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
"""Learned-comfort correction layer for the carrot curve-speed baseline.

StarPilot ``starpilot/curve_speed/`` learning/runtime port. The carrot geometric envelope
(``sunnypilot/carrot/curve_speed.py``) stays the baseline; the learned comfort curve only
scales the per-point lateral-acceleration budget when the master switch (``CurveSpeedLearning``)
is on and at least one sample has been learned. Disabled/unready -> behaviour identical to the
unmodified baseline.

``learning`` is Params-free and importable on any host; ``runtime`` pulls openpilot.common.params
(native lib), so it is imported by consumers (carrot_functions) directly rather than re-exported
here, keeping this package importable on PC hosts.
"""
from openpilot.sunnypilot.carrot.curve_speed_learning.learning import LearnedCurve, LoadResult, Bucket

__all__ = ['Bucket', 'LearnedCurve', 'LoadResult']
