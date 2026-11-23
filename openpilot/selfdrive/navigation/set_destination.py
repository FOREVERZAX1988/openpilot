#!/usr/bin/env python3
"""Set a navigation destination from the command line (ported from cp
selfdrive/navd/set_destination.py).

Adapted to sp's typed Params: NavDestination / NavDestinationWaypoints are
JSON-typed here, so put() takes the dict/list directly (cp json.dumps'd
strings into STRING params).
"""
import sys

from openpilot.common.params import Params

if __name__ == "__main__":
  params = Params()

  # set from google maps url
  if len(sys.argv) > 1:
    coords = sys.argv[1].split("/@")[-1].split("/")[0].split(",")
    dest = {
      "latitude": float(coords[0]),
      "longitude": float(coords[1])
    }
    params.put("NavDestination", dest)
    Params('/dev/shm/params').remove('NavDestinationTemporary')
    params.remove("NavDestinationWaypoints")
  else:
    print("Setting to Taco Bell")
    dest = {
      "latitude": 32.71160109904473,
      "longitude": -117.12556569985693,
    }
    params.put("NavDestination", dest)
    Params('/dev/shm/params').remove('NavDestinationTemporary')

    waypoints = [
      (-117.16020713111648, 32.71997612490662),
    ]
    params.put("NavDestinationWaypoints", waypoints)

    print(dest)
    print(waypoints)
