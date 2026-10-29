#!/usr/bin/env python3
import os
import subprocess

# NOTE: Do NOT import anything here that needs be built (e.g. params)
from openpilot.common.basedir import BASEDIR
from openpilot.common.spinner import Spinner
from openpilot.common.text_window import TextWindow
from openpilot.common.hardware import HARDWARE, AGNOS

def build() -> None:
  spinner = Spinner()
  spinner.update_progress(0, 100)

  HARDWARE.set_power_save(False)
  if AGNOS:
    os.sched_setaffinity(0, range(8))  # ensure we can use the isolcpus cores

  # building with all cores can result in using too much memory, so retry serially
  compile_output: list[bytes] = []
  for parallelism in ([], ["-j4"], ["-j1"]):
    compile_output.clear()
    with subprocess.Popen(["scons", *parallelism], cwd=BASEDIR, env={**os.environ, "PWD": BASEDIR}, stderr=subprocess.PIPE) as scons:
      assert scons.stderr is not None

      # Read progress from stderr and update spinner
      while scons.poll() is None:
        try:
          line = scons.stderr.readline()
          if line is None:
            continue
          line = line.rstrip()

          prefix = b'progress: '
          if line.startswith(prefix):
            progress = float(line[len(prefix):])
            spinner.update_progress(100 * min(1., progress / 100.), 100.)
          elif line.startswith(b'compiling '):
            # tinygrad 模型编译是最后一道工序（实测 37s + 44s），但 SConstruct 的
            # progress 只在「真正执行构建动作」的节点上累加，而 progress_total 数的是
            # 整个依赖图 —— 缓存命中或已存在的节点不回调，所以这条路走不到 100%，
            # 会停在一个固定的百分比（全新安装实测 64%）不动，然后 scons 直接
            # "done building targets"。用户看到的就是「卡在 64%」。
            # 这里让进度条在这个阶段动起来，别让人以为死了去拔电。
            spinner.update_progress(99., 100.)
          elif len(line):
            compile_output.append(line)
            print(line.decode('utf8', 'replace'))
        except Exception:
          pass

      # Drain and close the pipe before retrying or returning.
      for line in scons.stderr.read().split(b'\n'):
        line = line.rstrip()
        if len(line):
          compile_output.append(line)

    if scons.returncode == 0:
      # 同上：缓存命中率高时 progress 永远追不上 progress_total，编译明明成功了
      # 进度条却停在半路。这里明确收尾，避免屏幕停在一个假百分比上。
      spinner.update_progress(100., 100.)
      break

  os.sync()

  if scons.returncode != 0:
    # Build failed log errors
    error_s = b"\n".join(compile_output).decode('utf8', 'replace')

    # Show TextWindow
    spinner.close()
    if not os.getenv("CI"):
      with TextWindow("openpilot failed to build\n \n" + error_s) as t:
        t.wait_for_exit()
    exit(1)

if __name__ == "__main__":
  build()
