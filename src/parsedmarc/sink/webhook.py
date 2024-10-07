### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
from typing import Dict

# Installed
import requests
import requests.utils

# Package
from parsedmarc import __version__

# Local
from ..const import AppState
from ..report import AggregateReport, ForensicReport
from .base import BaseConfig, Sink


### CLASSES
### ============================================================================
class JsonWebhook(Sink):
    """Send reports to a HTTP endpoint as JSON

    *New in 9.0*.
    """

    config: JsonWebhookConfig

    def setup(self) -> None:
        if self._state != AppState.SHUTDOWN:
            raise RuntimeError("Sink is already running")
        self._state = AppState.SETTING_UP

        try:
            self.session = requests.Session()
            self.session.headers["User-Agent"] = (
                f"parsedmarc/{__version__} {requests.utils.default_user_agent}"
            )

            if self.config.http_headers:
                for key, value in self.config.http_headers.items():
                    self.session.headers[key] = value

        except:
            self._state = AppState.SETUP_ERROR
            raise

        self._state = AppState.RUNNING
        return

    def process_aggregate_report(self, report: AggregateReport) -> None:
        self.send_report(report.data, self.config.dmarc_aggregate_url)
        return

    def process_forensic_report(self, report: ForensicReport) -> None:
        self.send_report(report.data, self.config.dmarc_forensic_url)
        return

    def send_report(self, report: dict, url: str) -> None:
        r = self.session.post(url, json=report, timeout=self.config.http_timeout)
        r.raise_for_status()
        return


class JsonWebhookConfig(BaseConfig):
    """JsonWebhook Config"""

    http_headers: Dict[str, str] | None = None
    http_timeout: int = 60

    # URLs
    dmarc_aggregate_url: str
    dmarc_forensic_url: str
