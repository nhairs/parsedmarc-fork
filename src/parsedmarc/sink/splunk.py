### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Installed
from pydantic import BaseModel

# Local
from ..const import AppState
from ..report import AggregateReport, ForensicReport
from ..splunk import HECClient
from .base import BaseConfig, Sink


### CLASSES
### ============================================================================
class Splunk(Sink):
    """Sink that stores reports using the SPlunk HTTP Events Collector (HEC)

    References:

        - http://docs.splunk.com/Documentation/Splunk/latest/Data/AboutHEC
        - http://docs.splunk.com/Documentation/Splunk/latest/RESTREF/RESTinput#services.2Fcollector


    *New in 9.0*.
    """

    config: SplunkConfig

    def setup(self) -> None:
        if self._state != AppState.SHUTDOWN:
            raise RuntimeError("Sink is already running")
        self._state = AppState.SETTING_UP

        try:
            self.client = HECClient(
                url=self.config.client.url,
                access_token=self.config.client.access_token,
                verify=self.config.client.verify_ssl,
                timeout=self.config.client.timeout,
                index=self.config.index,
                source=self.config.source,
            )

        except:
            self._state = AppState.SETUP_ERROR
            raise

        self._state = AppState.RUNNING
        return

    def process_aggregate_report(self, report: AggregateReport) -> None:
        self.client.save_aggregate_reports_to_splunk(report)
        return

    def process_forensic_report(self, report: ForensicReport) -> None:
        self.client.save_forensic_reports_to_splunk(report)
        return


class SplunkConfig(BaseConfig):
    """Splunk Config"""

    client: SplunkClientConfig
    index: str
    source: str = "parsedmarc"


class SplunkClientConfig(BaseModel):
    """Splunk Client Config"""

    url: str
    access_token: str
    verify_ssl: bool = True
    timeout: int = 60
