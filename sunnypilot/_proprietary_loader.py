#!/usr/bin/env python3

import importlib
import sys
from types import ModuleType


class ProprietaryModuleMissing(ImportError):
  pass


def _is_private_module_missing(error: ModuleNotFoundError, private_module_name: str) -> bool:
  missing = error.name or ""
  root = private_module_name.split(".", 1)[0]
  return missing == private_module_name or missing == root or missing.startswith(f"{private_module_name}.")


def _publish_module_symbols(public_module: ModuleType, private_module: ModuleType) -> None:
  skip = {
    "__name__",
    "__package__",
    "__loader__",
    "__spec__",
    "__file__",
    "__cached__",
    "__builtins__",
  }

  for key, value in private_module.__dict__.items():
    if key in skip:
      continue
    public_module.__dict__[key] = value

  public_module.__dict__["__private_module__"] = private_module.__name__
  if "__all__" not in public_module.__dict__:
    public_module.__dict__["__all__"] = [k for k in private_module.__dict__ if not k.startswith("_")]


def load_private_module(public_module_name: str, private_module_name: str) -> ModuleType:
  public_module = sys.modules[public_module_name]

  try:
    private_module = importlib.import_module(private_module_name)
  except ModuleNotFoundError as error:
    if _is_private_module_missing(error, private_module_name):
      raise ProprietaryModuleMissing(
        f"missing proprietary module '{private_module_name}'. "
        "install the IQ Pilot private proprietary bundle into IQPILOT_PROPRIETARY_ROOT"
      ) from error
    raise

  _publish_module_symbols(public_module, private_module)
  return private_module