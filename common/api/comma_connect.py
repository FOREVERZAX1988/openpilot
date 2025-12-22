import os

from openpilot.common.api.base import BaseApi
#修改1：添加服务器切换按钮-切换服务器
from openpilot.common.params import Params

#API_HOST = os.getenv('API_HOST', 'https://api.konik.ai')
#API_HOST = "https://api.konik.ai" if Params().get_bool("UseKonikServer") else "https://api.commadotai.com"

class CommaConnectApi(BaseApi):
  def __init__(self, dongle_id):
    API_HOST = "https://api.konik.ai" if Params().get_bool("UseKonikServer") else "https://api.commadotai.com"
    super().__init__(dongle_id, API_HOST)
    self.user_agent = "openpilot-"
