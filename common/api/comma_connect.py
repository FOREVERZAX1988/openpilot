import os

from openpilot.common.api.base import BaseApi

from openpilot.common.params import Params

def get_api_host():
    params = Params()
    try:
        server_type = params.get("ServerType", "konik")
    except Exception:
        server_type = "konik"  # 异常时使用默认值
    if server_type == "comma":
        return os.getenv('API_HOST', 'https://api.commadotai.com')
    else:
        return os.getenv('API_HOST', 'https://api.konik.ai')

API_HOST = get_api_host()


class CommaConnectApi(BaseApi):
    def __init__(self, dongle_id):
        super().__init__(dongle_id, API_HOST)
        self.user_agent = "openpilot-"
