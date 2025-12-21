import os
import requests
from requests.adapters import HTTPAdapter, Retry
# 修改api.py中的API_HOST定义
# 原代码:
# API_HOST = os.getenv('API_HOST', 'https://api.commadotai.com')
# 替换为:
from openpilot.common.params import Params

def get_api_host():
    params = Params()
    server_type = params.get("ServerType", "konik")
    if server_type == "comma":
        return os.getenv('API_HOST', 'https://api.commadotai.com')
    else:
        return os.getenv('API_HOST', 'https://api.konik.ai')

API_HOST = get_api_host()

# TODO: this should be merged into common.api

class CommaApi:
  def __init__(self, token=None):
    self.session = requests.Session()
    self.session.headers['User-agent'] = 'OpenpilotTools'
    if token:
      self.session.headers['Authorization'] = 'JWT ' + token

    retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    self.session.mount('https://', HTTPAdapter(max_retries=retries))

  def request(self, method, endpoint, **kwargs):
    with self.session.request(method, API_HOST + '/' + endpoint, **kwargs) as resp:
      resp_json = resp.json()
      if isinstance(resp_json, dict) and resp_json.get('error'):
        if resp.status_code in [401, 403]:
          raise UnauthorizedError('Unauthorized. Authenticate with tools/lib/auth.py')

        e = APIError(str(resp.status_code) + ":" + resp_json.get('description', str(resp_json['error'])))
        e.status_code = resp.status_code
        raise e
      return resp_json

  def get(self, endpoint, **kwargs):
    return self.request('GET', endpoint, **kwargs)

  def post(self, endpoint, **kwargs):
    return self.request('POST', endpoint, **kwargs)

class APIError(Exception):
  pass

class UnauthorizedError(Exception):
  pass
