import os

from openpilot.common.api.base import BaseApi

def get_api_host():
    from openpilot.common.params import Params
    return "https://api.konik.ai" if Params().get_bool("UseKonikServer") else "https://api.commadotai.com"


class CommaConnectApi(BaseApi):
  def __init__(self, dongle_id):
    super().__init__(dongle_id, get_api_host())
    self.user_agent = "openpilot-"
