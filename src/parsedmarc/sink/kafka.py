### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
import ssl
from typing import List

# Installed
from pydantic import BaseModel

# Local
from .. import kafkaclient
from ..const import AppState
from ..report import AggregateReport, ForensicReport
from .base import BaseConfig, Sink


### CLASSES
### ============================================================================
class Kafka(Sink):
    """Stores reports in Kafka.

    *New in 9.0*.
    """

    config: KafkaConfig

    def setup(self) -> None:
        if self._state != AppState.SHUTDOWN:
            raise RuntimeError("Sink is already running")
        self._state = AppState.SETTING_UP

        try:
            if self.config.client.skip_certificate_verification:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            else:
                ssl_context = None

            self.client = kafkaclient.KafkaClient(
                kafka_hosts=self.config.client.hosts,
                ssl=self.config.client.ssl,
                username=self.config.client.username,
                password=self.config.client.password,
                ssl_context=ssl_context,
            )

        except:
            self._state = AppState.SETUP_ERROR
            raise

        self._state = AppState.RUNNING
        return

    def process_aggregate_report(self, report: AggregateReport) -> None:
        self.client.save_aggregate_reports_to_kafka(report, self.config.aggregate_report_topic)
        return

    def process_forensic_report(self, report: ForensicReport) -> None:
        self.client.save_forensic_reports_to_kafka(report, self.config.forensic_report_topic)
        return


## Config
## -----------------------------------------------------------------------------
class KafkaConfig(BaseConfig):
    """Kafka Config"""

    client: KafkaClient
    aggregate_report_topic: str
    forensic_report_topic: str


class KafkaClient(BaseModel):
    hosts: List[str]
    ssl: bool = True
    skip_certificate_verification: bool = False
    username: str | None = None
    password: str | None = None
