"""Install openpilot from any git repository (github / gitee / cnb / ...).

Carrot library for the AGNOS setup wizard: mirrors the flow of
tools/release/install.sh so the custom-software screen can install arbitrary
"owner/branch" targets from real git repositories instead of only
installer.comma.ai builds:

  resolve_git_repo()  — probe known hosts in parallel, first hit wins
                        (github direct → github via gh-proxy → gitee → cnb)
  install_from_git()  — git clone --depth=1 → submodules → LFS assets →
                        validate → replace /data/openpilot (old tree backed
                        up) → write /data/continue.sh → inject SSH keys

Pure stdlib; no hardware/UI dependencies so it can run inside the setup
zipapp. The callers own the user-facing status/error texts (and their
translations); this module reports phase keys and raises GitInstallError.
"""
import os
import re
import shutil
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

GIT_REPO_HOSTS = (
  "https://github.com",
  "https://gitee.com",
  "https://cnb.cool",
)
# gh-proxy only mirrors github.com git traffic; other hosts are always direct.
GH_PROXY_PREFIX = "https://gh-proxy.com/"
PROXIED_HOSTS = {"github.com", "raw.githubusercontent.com"}

INSTALL_PATH = "/data/openpilot"
TMP_PATH = "/data/tmppilot"
BACKUP_PATH = "/data/safe_test/old_openpilot_git_install"
CONTINUE_PATH = "/data/continue.sh"
PROBE_TIMEOUT = 8.0
# 2025-01-01: git/TLS fail on an invalid RTC (fresh device after power loss).
MIN_VALID_TIME = 1735689600

LFS_POINTER_PROBES = (
  "openpilot/selfdrive/assets/fonts/Inter-Regular.ttf",
  "openpilot/selfdrive/assets/fonts/OpFont-Regular.otf",
)


class GitInstallError(Exception):
  def __init__(self, kind: str, detail: str = ""):
    super().__init__(f"{kind}: {detail}" if detail else kind)
    self.kind = kind
    self.detail = detail


def proxied_url(url: str) -> str:
  if url.partition("://")[2].partition("/")[0] in PROXIED_HOSTS and not url.startswith(GH_PROXY_PREFIX):
    return GH_PROXY_PREFIX + url
  return url


def resolve_git_repo(owner: str, branch: str) -> str | None:
  """Return a clone URL where owner/openpilot@branch exists, or None.

  All hosts are probed in parallel; candidate order is the priority
  (github direct, github via gh-proxy, gitee, cnb).
  """
  # git ls-remote over HTTPS fails certificate validation on an RTC-less
  # device (clock at 1970), which silently made EVERY probe fail and the
  # wizard fall back to installer.comma.ai. Sync the clock first.
  sync_clock()

  candidates: list[str] = []
  for host in GIT_REPO_HOSTS:
    url = f"{host}/{owner}/openpilot.git"
    candidates.append(url)
    if "github.com" in host:
      candidates.append(GH_PROXY_PREFIX + url)

  def probe(url: str) -> bool:
    try:
      result = subprocess.run(
        ["git", "ls-remote", "--exit-code", url, f"refs/heads/{branch}"],
        timeout=PROBE_TIMEOUT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
      return result.returncode == 0
    except Exception:
      return False

  with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
    for url, found in zip(candidates, pool.map(probe, candidates)):
      if found:
        return url
  return None


def sync_clock() -> None:
  """Best-effort HTTP-date clock sync (HTTPS validation itself needs a valid clock)."""
  if time.time() >= MIN_VALID_TIME:
    return
  for url in ("http://www.qq.com", "http://www.baidu.com", "http://github.com"):
    try:
      request = urllib.request.Request(url, method="HEAD")
      with urllib.request.urlopen(request, timeout=5) as response:
        http_date = response.headers.get("date")
      if http_date:
        subprocess.run(["sudo", "date", "-s", http_date], capture_output=True, timeout=10)
        if time.time() >= MIN_VALID_TIME:
          return
    except Exception:
      continue


def _stream_progress(cmd: list[str], on_progress=None) -> None:
  """Run a git command, parsing its --progress output into percentages."""
  try:
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, errors="replace")
  except FileNotFoundError as e:
    raise GitInstallError("git_missing", str(e))
  assert proc.stderr is not None
  for line in proc.stderr:
    # "Receiving objects:  34% (1234/3600)" etc. (git rewrites the line with \r)
    if on_progress is not None:
      for token in line.split("\r"):
        m = re.search(r":\s+(\d{1,3})%", token)
        if m:
          on_progress(int(m.group(1)))
  returncode = proc.wait()
  if returncode != 0:
    raise GitInstallError("git_failed", f"exit {returncode}: {' '.join(cmd[:4])} ...")


def install_from_git(clone_url: str, branch: str | None = None, on_status=None, on_progress=None) -> None:
  """Clone + submodules + LFS + validate + replace /data/openpilot + continue.sh.

  Raises GitInstallError(kind, detail) on failure. on_status receives phase
  keys ("clone" | "submodules" | "lfs" | "install"); on_progress receives 0-100.
  """
  sync_clock()

  if on_status is not None:
    on_status("clone")
  if on_progress is not None:
    on_progress(0)
  shutil.rmtree(TMP_PATH, ignore_errors=True)
  cmd = ["git", "clone", "--progress", clone_url, "--depth=1"]
  if branch:
    cmd += ["-b", branch]
  cmd.append(TMP_PATH)
  try:
    _stream_progress(cmd, on_progress)
  except GitInstallError as e:
    raise GitInstallError("clone_failed", e.detail)

  if os.path.isfile(os.path.join(TMP_PATH, ".gitmodules")):
    if on_status is not None:
      on_status("submodules")
    if on_progress is not None:
      on_progress(0)
    try:
      _stream_progress(["git", "-C", TMP_PATH, "submodule", "update", "--init",
                        "--progress", "--depth=1", "--recursive"], on_progress)
    except GitInstallError as e:
      raise GitInstallError("submodule_failed", e.detail)

  # LFS assets: fonts/models are pointer files until pulled (submodules too).
  subprocess.run(["git", "-C", TMP_PATH, "lfs", "install", "--local"], capture_output=True)
  try:
    lfs_files = subprocess.run(["git", "-C", TMP_PATH, "lfs", "ls-files"], capture_output=True,
                               text=True, timeout=60).stdout.strip()
  except Exception:
    lfs_files = ""
  if lfs_files:
    if on_status is not None:
      on_status("lfs")
    if on_progress is not None:
      on_progress(0)
    result = subprocess.run(["git", "-C", TMP_PATH, "lfs", "pull"], capture_output=True,
                            text=True, timeout=1800)
    if result.returncode != 0:
      raise GitInstallError("lfs_failed", (result.stderr or "").strip()[-400:])
    subprocess.run(["git", "-C", TMP_PATH, "submodule", "foreach", "--recursive",
                    "git", "lfs", "pull"], capture_output=True, timeout=1800)

  # validate the tree before touching the current install
  if not os.path.isfile(os.path.join(TMP_PATH, "launch_openpilot.sh")):
    raise GitInstallError("not_openpilot", "launch_openpilot.sh missing")
  for probe in LFS_POINTER_PROBES:
    probe_path = os.path.join(TMP_PATH, probe)
    if os.path.isfile(probe_path):
      with open(probe_path, "rb") as f:
        if f.read(30).startswith(b"version https://git-lfs"):
          raise GitInstallError("lfs_failed", f"{probe} is still a pointer file")

  if on_status is not None:
    on_status("install")
  if on_progress is not None:
    on_progress(0)
  try:
    os.makedirs(os.path.dirname(BACKUP_PATH), exist_ok=True)
    if os.path.isdir(INSTALL_PATH):
      shutil.rmtree(BACKUP_PATH, ignore_errors=True)
      os.rename(INSTALL_PATH, BACKUP_PATH)
    os.rename(TMP_PATH, INSTALL_PATH)
    for name in os.listdir(INSTALL_PATH):
      if name.startswith("launch_") and name.endswith(".sh"):
        os.chmod(os.path.join(INSTALL_PATH, name), 0o755)
  except OSError as e:
    raise GitInstallError("install_failed", str(e))

  write_continue_sh()
  inject_ssh_keys()


def write_continue_sh() -> None:
  content = "#!/usr/bin/env bash\ncd /data/openpilot\nexec ./launch_openpilot.sh\n"
  tmp = CONTINUE_PATH + ".new"
  with open(tmp, "w", encoding="utf-8") as f:
    f.write(content)
  os.chmod(tmp, 0o755)
  os.replace(tmp, CONTINUE_PATH)


def inject_ssh_keys() -> None:
  """Mirror tools/release/install.sh: inject the maintainer SSH keys so the
  device stays reachable after a git install (best effort, never fatal)."""
  key_urls = (
    "https://cnb.cool/mouxancnb/openpilot/-/git/raw/test/tools/release/github_keys.txt",
    proxied_url("https://raw.githubusercontent.com/mouxangithub/openpilot/refs/heads/test/tools/release/github_keys.txt"),
  )
  try:
    params_dir = "/data/params/d"
    os.makedirs(params_dir, exist_ok=True)
    for url in key_urls:
      try:
        with urllib.request.urlopen(url, timeout=15) as response:
          data = response.read()
        if data.count(b"ssh-") >= 1:
          with open(os.path.join(params_dir, "GithubSshKeys"), "wb") as f:
            f.write(data)
          with open(os.path.join(params_dir, "SshEnabled"), "w") as f:
            f.write("1")
          return
      except Exception:
        continue
  except Exception:
    pass
