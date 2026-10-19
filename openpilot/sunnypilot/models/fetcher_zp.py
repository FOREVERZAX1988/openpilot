"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot import jetlink_adapter
from openpilot.sunnypilot.models.fetcher import ModelCache, ModelFetcher

# stamped on the big-model catalog: whether it carries the newer catalogs' models
EXTENDED_KEY = "extended"


class BigCatalogCache(ModelCache):
  """The big-model catalog's cache, expired when it was fetched for other hardware: a chestnut
  coming or going changes whether it is extended, and the cache would otherwise hide that for an
  hour. Once per change: offline, the refetch fails and the cache stands until it expires."""

  def __init__(self, params: Params, suffix: str):
    super().__init__(params, suffix=suffix)
    self._refetched_extends: bool | None = None
    # armed by the fetcher: the change's one attempt must reach the network, so the
    # fetcher drops the backoff its last failure left here (see ModelFetcherZP)
    self.on_change = None

  def get(self) -> tuple[dict, bool]:
    cached_data, is_expired = super().get()
    if cached_data and not is_expired:
      extends = jetlink_adapter.should_extend_catalog()
      if bool(cached_data.get(EXTENDED_KEY)) != extends and self._refetched_extends != extends:
        self._refetched_extends = extends
        cloudlog.warning(f"big-model catalog was fetched {'without' if extends else 'with'} the newer catalogs; refetching")
        is_expired = True
        if self.on_change is not None:
          self.on_change()
    return cached_data, is_expired


class ModelFetcherZP(ModelFetcher):
  """sunnypilot's fetcher with the big-model catalog extended through jetlink: without a chestnut
  it also lists the big models newer catalogs publish, so one released after this build can still
  be picked for an accelerator."""

  def __init__(self, params: Params):
    super().__init__(params)
    cache = BigCatalogCache(params, self.MODEL_SOURCES["chestnut"][1])
    # A change of hardware is a new event, not a retry: drop the boot-time backoff the last
    # failed fetch armed for this source, so the one attempt a change is owed is not swallowed
    # by it. BigCatalogCache latches once per change, so this cannot storm the mirrors.
    # (fork rule: upstream has no backoff at all and simply asks again on every change -- we
    # keep the 1970-clock storm guard and only exempt the attempt a change earns.)
    cache.on_change = lambda: (self._retry_at.pop("chestnut", None), self._failures.pop("chestnut", None))
    self.model_caches["chestnut"] = cache

  def _extension_stale(self, cached_data: dict) -> bool:
    # BigCatalogCache.get() already expires the catalog once per change, on its
    # own memory: leaving the base class's check in place too meant the second
    # tick after a chestnut comes or goes refetched a second time, offline for
    # nothing
    return False

  def _extend_catalog(self, source: str, json_data: dict) -> dict:
    if source != "chestnut":
      return json_data
    extended = jetlink_adapter.should_extend_catalog()
    return {**(jetlink_adapter.extend_catalog(json_data) if extended else json_data), EXTENDED_KEY: extended}
