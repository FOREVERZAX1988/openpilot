#!/usr/bin/env python3
"""Freeze the scene the moment an onroad alert fires.

Some alerts are gone before anyone can look at them: locationdTemporaryError
lifts by itself after the locationd budget decays, commIssue clears as soon as
the link recovers, and by the time a message reaches someone with a keyboard the
state that caused it no longer exists. This daemon keeps the evidence.

It watches selfdriveState.alertType (100 Hz) and onroadEvents (1 Hz) for a list
of fault events. On the transition into one it writes a small JSON snapshot --
the event, the flags that drive it, the tail of the swaglog WARNING/ERROR lines,
the process table and the current route/segment -- and on the transition out it
writes a second, shorter one.

Writes to /data/diag_events/:
  <local time>-<event>-raised.json    first sighting, full snapshot
  <local time>-<event>-cleared.json   it went away again
  index.log                           one line per snapshot, greppable

Read-only with respect to the car: it subscribes to messages and never touches
CAN or the panda. Snapshots are a few KB each and are pruned to the newest
MAX_FILES.

Subscriptions are plain sub_sock + drain_sock rather than SubMaster: with a poll
service that is silent (selfdriveState while parked) SubMaster.update() only
tries one non-polled socket per call, which made event pickup unreliable.
"""
import glob
import json
import os
import subprocess
import time
from datetime import datetime

from openpilot.cereal import log, messaging
from openpilot.common.swaglog import cloudlog

OUT_DIR = '/data/diag_events'
INDEX = os.path.join(OUT_DIR, 'index.log')

SERVICES = ['selfdriveState', 'onroadEvents', 'deviceState',
            'carState', 'modelV2', 'deviceMotion']

POLL_S = 0.5
MAX_FILES = 300
SWAGLOG_BYTES = 150_000
SWAGLOG_LINES = 40
REPEAT_GUARD_S = 5.0

# Fault events worth a snapshot, taken from the live OnroadEvent schema.
# Operational ones (steerOverride, gasOverride, personalityChanged,
# bigModelReady, lkasEnable, laneChangeBlocked, resumeBlocked, ...) are
# deliberately absent: they are normal driving feedback and would bury the
# signal. main() re-checks this set against the schema and logs any drift.
WATCHED = {
  # localisation / learning
  'locationdTemporaryError', 'paramsdTemporaryError', 'posenetInvalid',
  'calibrationInvalid',
  # messaging / processes
  'commIssue', 'commIssueAvgFreq', 'processNotRunning', 'sensorDataInvalid',
  'modeldLagging', 'modeldLaggingMild', 'selfdrivedLagging', 'bigModelFailed',
  'canBusMissing', 'canError',
  # car / controls
  'cruiseMismatch', 'controlsMismatch', 'accFaulted', 'steerUnavailable',
  'steerTempUnavailable', 'radarFault', 'radarTempUnavailable',
  'vehicleSensorsInvalid',
}


def _now_str() -> str:
  return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _safe(name: str) -> str:
  return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in name)


def current_segment():
  """Newest route/segment on disk, so a snapshot points at a replayable rlog."""
  try:
    dirs = glob.glob('/data/media/0/realdata/0*--*')
    if not dirs:
      return None, None
    latest = max(dirs, key=os.path.getmtime)
    route, _, seg = os.path.basename(latest).rpartition('--')
    return route or None, int(seg) if seg.isdigit() else None
  except Exception:
    return None, None


def swaglog_tail():
  """Recent WARNING/ERROR lines, parsed down to time/daemon/message."""
  try:
    files = sorted(glob.glob('/data/log/swaglog.*'), key=os.path.getmtime)
    if not files:
      return []
    with open(files[-1], 'rb') as f:
      f.seek(0, 2)
      size = f.tell()
      f.seek(max(0, size - SWAGLOG_BYTES))
      data = f.read().decode('utf-8', 'replace')
    out = []
    for line in data.splitlines():
      if '"level": "WARNING"' not in line and '"level": "ERROR"' not in line:
        continue
      try:
        j = json.loads(line)
        out.append({
          't': round(j.get('created', 0), 2),
          'level': j.get('level'),
          'daemon': (j.get('ctx') or {}).get('daemon'),
          # swaglog stores the message under msg$s (logbook names the field that way)
          'msg': j.get('msg$s') or j.get('msg') or '',
        })
      except Exception:
        out.append({'raw': line[:300]})
    return out[-SWAGLOG_LINES:]
  except Exception:
    return []


def proc_top():
  """Who is eating the CPU. A loaded C3 is a common cause of missed deadlines."""
  try:
    out = subprocess.run(['ps', '-eo', 'pcpu,rss,args', '--sort=-pcpu', '--no-headers'],
                         capture_output=True, text=True, timeout=3).stdout
    rows = []
    for line in out.splitlines()[:8]:
      parts = line.split(None, 2)
      if len(parts) == 3:
        rows.append('%s%% %sKB %s' % (parts[0], parts[1], parts[2][:90]))
      else:
        rows.append(' '.join(line.split()))
    return rows
  except Exception:
    return []


def read_state(latest):
  st = {}
  cs = latest.get('carState')
  if cs is not None:
    st['vEgo'] = round(float(cs.vEgo), 3)
    st['steerDeg'] = round(float(cs.steeringAngleDeg), 2)
    st['gear'] = str(getattr(cs.gearShifter, 'raw', ''))
    st['standstill'] = bool(cs.standstill)
    st['cruiseEnabled'] = bool(cs.cruiseState.enabled)
    st['cruiseAvailable'] = bool(cs.cruiseState.available)
  ss = latest.get('selfdriveState')
  if ss is not None:
    st['enabled'] = bool(ss.enabled)
    st['active'] = bool(ss.active)
    st['alertType'] = str(ss.alertType)
    st['alertStatus'] = str(ss.alertStatus)
    st['alertText1'] = str(ss.alertText1)
  dm = latest.get('deviceMotion')
  if dm is not None:
    st['inputsOK'] = bool(dm.inputsOK)
    st['posenetOK'] = bool(dm.posenetOK)
    st['sensorsOK'] = bool(dm.sensorsOK)
    st['yawRateZ'] = round(float(dm.angularVelocityDevice.z), 4)
  mv = latest.get('modelV2')
  if mv is not None:
    st['bigModel'] = bool(mv.big)
  ds = latest.get('deviceState')
  if ds is not None:
    st['started'] = bool(ds.started)
    st['onroad'] = bool(ds.onroad)
    st['thermalStatus'] = str(ds.thermalStatus)
    st['batteryPercent'] = round(float(ds.batteryPercent), 1)
  return st


def watched_now(latest) -> set:
  """Fault events currently reported, from both the alert and the event list."""
  names = set()
  ss = latest.get('selfdriveState')
  if ss is not None:
    a = str(ss.alertType)
    if a in WATCHED:
      names.add(a)
  oe = latest.get('onroadEvents')
  if oe is not None:
    for ev in oe:
      n = str(ev.name)
      if n in WATCHED:
        names.add(n)
  return names


def snapshot(latest, event, kind, swaglog_cache):
  wall = time.time()
  route, seg = current_segment()
  swaglog_cache['at'], swaglog_cache['lines'] = wall, swaglog_tail()
  data = {
    'utc_offset_s': -time.timezone,
    'local': _now_str(),
    'wall': round(wall, 3),
    'kind': kind,
    'event': event,
    'route': route,
    'segment': seg,
    'state': read_state(latest),
    'swaglog': swaglog_cache['lines'],
    'top': proc_top(),
  }
  try:
    os.makedirs(OUT_DIR, exist_ok=True)
    fn = os.path.join(OUT_DIR, '%s-%s-%s.json' % (_now_str().replace(':', '').replace(' ', '-'), _safe(event), kind))
    with open(fn, 'w') as f:
      json.dump(data, f, ensure_ascii=False, indent=1)
      f.flush()
      os.fsync(f.fileno())
    st = data['state']
    with open(INDEX, 'a') as f:
      f.write('%s %-7s %-30s %s seg%s v=%.2f OK=%s/%s/%s big=%s alert=%s\n' % (
        data['local'], kind, event, route or '?', seg if seg is not None else '?',
        st.get('vEgo', float('nan')),
        st.get('inputsOK'), st.get('posenetOK'), st.get('sensorsOK'),
        st.get('bigModel'), st.get('alertType')))
      f.flush()
      os.fsync(f.fileno())
    return fn
  except Exception as e:
    cloudlog.warning('diag_watchd: snapshot failed: %r' % (e,))
    return None


def prune():
  try:
    files = sorted(glob.glob(os.path.join(OUT_DIR, '*.json')), key=os.path.getmtime)
    for f in files[:-MAX_FILES]:
      os.remove(f)
  except Exception:
    pass


def main():
  unknown = WATCHED - set(log.OnroadEvent.EventName.schema.enumerants)
  if unknown:
    # names that drifted or never existed; keep running with the rest
    cloudlog.warning('diag_watchd: unknown event names ignored: %s' % (sorted(unknown),))

  socks = {s: messaging.sub_sock(s, conflate=True, timeout=20) for s in SERVICES}
  latest = {}
  active = set()
  last_write = {}
  swaglog_cache = {'at': 0.0, 'lines': []}
  last_prune = 0.0

  while True:
    try:
      for name, sock in socks.items():
        msgs = messaging.drain_sock(sock)
        if msgs:
          latest[name] = getattr(msgs[-1], name)

      now = time.time()
      present = watched_now(latest)

      for ev in sorted(present - active):
        if now - last_write.get(ev, 0.0) < REPEAT_GUARD_S:
          continue
        last_write[ev] = now
        fn = snapshot(latest, ev, 'raised', swaglog_cache)
        if fn:
          cloudlog.warning('diag_watchd: captured %s -> %s' % (ev, fn))
      active |= present

      for ev in sorted(active - present):
        active.discard(ev)
        if now - last_write.get(ev, 0.0) < REPEAT_GUARD_S:
          continue
        last_write[ev] = now
        snapshot(latest, ev, 'cleared', swaglog_cache)

      if now - last_prune > 60.0:
        last_prune = now
        prune()
    except Exception as e:
      cloudlog.warning('diag_watchd: loop error: %r' % (e,))
    time.sleep(POLL_S)


if __name__ == '__main__':
  main()
