import requests

from .parser import parse_kjpl_html
from .schemas import KJPLRate


class KJPLClient:
    BASE_URL = "http://www.kjpl.in/"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def fetch_rates(self) -> KJPLRate:
        response = requests.get(
            self.BASE_URL,
            timeout=self.timeout,
            headers={
                "User-Agent": "GoldSense-AI/1.0"
            },
        )

        response.raise_for_status()

        return parse_kjpl_html(response.text)