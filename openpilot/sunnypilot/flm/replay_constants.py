"""Constants extracted from StarPilot controller_replay.py (the 1,724-line replay
module is deliberately not ported; only these evidence-history bounds are needed
by the event persistence chain). Verbatim values.
"""

MAX_FRAME_GAP_NS = 50_000_000
MAX_REPLAY_FRAMES = 60_000  # Ten minutes, the independent evidence history bound.
