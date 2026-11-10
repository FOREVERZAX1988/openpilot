"""Reviewed local driving-model catalog — single bundled entry.

Adapted from StarPilot starpilot/models/catalog.py: our fork has no model
selection manager or catalog.json, so model_entries() resolves exactly the
bundled driving model. The artifact sha is carried by the receipt itself (it
hashes the installed file at startup); the catalog row stays descriptive.
This module never loads model artifacts.
"""

from dataclasses import dataclass


BUNDLED_CURRENT = "bundled-current"


@dataclass(frozen=True)
class ModelEntry:
  model_id: str
  name: str
  source_sha256: str
  source_path: str
  compiler_revision: str
  artifact_abi: str
  selectable: bool
  version: str = "current"
  uses_external_gpu: bool = False


BUNDLED = (
  ModelEntry(
    model_id=BUNDLED_CURRENT,
    name="bundled driving model",
    source_sha256="",  # the receipt records the hash of the actual installed artifact
    source_path="openpilot/selfdrive/modeld/models/driving_tinygrad.pkl",
    compiler_revision="",
    artifact_abi="tinygrad_single_v1_arena",
    selectable=True,
  ),
)

BY_ID = {entry.model_id: entry for entry in BUNDLED}


def model_entries(root=None) -> dict:
  """Resolve validated cached metadata without mutating the bundled catalog."""
  return dict(BY_ID)


def resolve_selection(requested_id, *, root=None) -> ModelEntry:
  """Resolve a saved request; absence means the bundled model, never an unknown ID."""
  model_id = BUNDLED_CURRENT if requested_id in (None, BUNDLED_CURRENT) else requested_id
  entries = model_entries(root)
  if not isinstance(model_id, str) or model_id not in entries or not entries[model_id].selectable:
    raise ValueError("unqualified driving-model selection")
  return entries[model_id]
