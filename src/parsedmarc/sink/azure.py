### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Installed
import azure.identity
import azure.monitor.ingestion

# Local
from ..const import AppState
from ..report import AggregateReport, ForensicReport
from .base import BaseConfig, Sink


### CLASSES
### ============================================================================
class LogAnalytics(Sink):
    """Stores reports in Azure Log Analytics.

    References:
      - https://learn.microsoft.com/en-us/azure/azure-monitor/logs/logs-ingestion-api-overview

    *New in 9.0*.
    """

    config: LogAnalyticsConfig

    def setup(self) -> None:
        if self._state != AppState.SHUTDOWN:
            raise RuntimeError("Sink is already running")
        self._state = AppState.SETTING_UP

        try:
            self._credential = azure.identity.ClientSecretCredential(
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
                tenant_id=self.config.tenant_id,
            )
            self.logs_client = azure.monitor.ingestion.LogsIngestionClient(
                self.config.data_collection_endpoint,
                credential=self._credential,
            )

        except:
            self._state = AppState.SETUP_ERROR
            raise

        self._state = AppState.RUNNING
        return

    def process_aggregate_report(self, report: AggregateReport) -> None:
        self.logs_client.upload(
            self.config.data_collection_rule_id,
            self.config.aggregate_report_stream,
            [report.data],
        )
        return

    def process_forensic_report(self, report: ForensicReport) -> None:
        self.logs_client.upload(
            self.config.data_collection_rule_id,
            self.config.forensic_report_stream,
            [report.data],
        )
        return


## Config
## -----------------------------------------------------------------------------
class LogAnalyticsConfig(BaseConfig):
    """LogAnalytics Config"""

    client_id: str
    client_secret: str
    tenant_id: str
    data_collection_endpoint: str
    data_collection_rule_id: str
    aggregate_report_stream: str
    forensic_report_stream: str
