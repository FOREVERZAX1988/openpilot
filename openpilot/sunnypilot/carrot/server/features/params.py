"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
"""Parameter REST API: what the companion app uses to read and write settings.

Wire contract (identical to CarrotPilot's, which navipilot / CP 搭子 implements against):

    POST /api/param_set    {"name": "ExperimentalMode", "value": 1}
      -> 200 {"ok": true, "name": ..., "value": <stored>}
      -> 400 {"ok": false, "error": "..."}

    GET  /api/params_bulk?names=ExperimentalMode,IsMetric
      -> 200 {"ok": true, "values": {"ExperimentalMode": 0, "IsMetric": 1}}
      -> 400 {"ok": false, "error": "missing names"}

Client errors are 400, not 500: an unknown key or a value of the wrong type is the
caller's mistake, and navipilot surfaces the `error` string to the driver.
"""

from aiohttp import web

from ..services.params import ParamWriteError, get_param_values, json_safe, set_param_value

PARAMS_KEY = web.AppKey("carrot_server_params")


async def api_params_bulk(request: web.Request) -> web.Response:
  names = [name.strip() for name in request.query.get("names", "").split(",") if name.strip()]
  if not names:
    return web.json_response({"ok": False, "error": "missing names"}, status=400)

  params = request.app[PARAMS_KEY]
  values = get_param_values(params, [name for name in names if name != "DeviceType"])
  # DeviceType is not a parameter: it is read from the hardware layer, and the app asks
  # for it alongside real settings, so it is answered here rather than 400'd.
  if "DeviceType" in names:
    try:
      # sunnypilot keeps HARDWARE in common.hardware; openpilot upstream has it under
      # system.hardware. Try both so the answer does not depend on which layout is live.
      try:
        from openpilot.common.hardware import HARDWARE
      except ImportError:
        from openpilot.system.hardware import HARDWARE

      values["DeviceType"] = HARDWARE.get_device_type()
    except Exception:
      values["DeviceType"] = "unknown"
  return web.json_response({"ok": True, "values": values})


async def api_param_set(request: web.Request) -> web.Response:
  try:
    body = await request.json()
  except Exception:
    return web.json_response({"ok": False, "error": "invalid json"}, status=400)

  if not isinstance(body, dict):
    return web.json_response({"ok": False, "error": "body must be a JSON object"}, status=400)

  name = body.get("name")
  if "value" not in body:
    return web.json_response({"ok": False, "error": "missing value"}, status=400)

  params = request.app[PARAMS_KEY]
  try:
    stored = set_param_value(params, name, body.get("value"))
  except ParamWriteError as exc:
    return web.json_response({"ok": False, "error": str(exc)}, status=400)

  return web.json_response({"ok": True, "name": name, "value": json_safe(stored)})


async def api_params_ping(request: web.Request) -> web.Response:
  """Cheap liveness probe for the app's connection state and for our own smoke tests."""
  return web.json_response({"ok": True, "service": "carrot_server", "api": ["param_set", "params_bulk"]})


def register(app: web.Application) -> None:
  app.router.add_post("/api/param_set", api_param_set)
  app.router.add_get("/api/params_bulk", api_params_bulk)
  app.router.add_get("/api/param_ping", api_params_ping)
