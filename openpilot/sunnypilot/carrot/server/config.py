"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
"""Configuration for the carrot API server."""

import os

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 7000

# CarrotPilot's launcher can hand the web server off to an external launcher
# (`CARROT_WEB_EXTERNAL=1`); the manager then must not start this process.
CARROT_WEB_EXTERNAL = os.getenv("CARROT_WEB_EXTERNAL") == "1"

# Core affinity for the server. Same default as CarrotPilot: share the background core
# pool rather than the realtime control core (4, which card/controlsd/selfdrived own).
DEFAULT_CORES = (0, 1, 2, 3)
