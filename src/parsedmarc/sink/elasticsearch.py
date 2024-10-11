### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
from typing import List, Literal

# Installed
from pydantic import BaseModel

# Local
from ..const import AppState
from ..elastic import AlreadySaved, ElasticsearchClient
from ..report import AggregateReport, ForensicReport
from .base import BaseConfig, Sink


### CLASSES
### ============================================================================
class Elasticsearch(Sink):
    """Stores reports in Elasticsearch.

    *New in 9.0*.
    """

    config: ElasticsearchConfig

    def setup(self) -> None:
        if self._state != AppState.SHUTDOWN:
            raise RuntimeError("Sink is already running")
        self._state = AppState.SETTING_UP

        try:
            self.client = ElasticsearchClient(**dict(self.config.client))
            self.client.migrate_indexes()

        except:
            self._state = AppState.SETUP_ERROR
            raise

        self._state = AppState.RUNNING
        return

    def cleanup(self) -> None:
        super().cleanup()
        self.client.client.close()
        return

    def process_aggregate_report(self, report: AggregateReport) -> None:
        try:
            self.client.save_aggregate_report_to_elasticsearch(report)
        except AlreadySaved as e:
            if self.config.on_duplicate == "discard":
                self.info(f"Discarding duplicate report: {e!r}")
                return
            raise
        return

    def process_forensic_report(self, report: ForensicReport) -> None:
        try:
            self.client.save_forensic_report_to_elasticsearch(report)
        except AlreadySaved as e:
            if self.config.on_duplicate == "discard":
                self.info(f"Discarding duplicate report: {e!r}")
                return
            raise
        return


class ElasticsearchConfig(BaseConfig):
    """Elasticsearch Config"""

    client: ElasticsearchClientConfig
    on_duplicate: Literal["discard"] = "discard"  # TODO: implement update logic and add


class ElasticsearchClientConfig(BaseModel):
    hosts: str | List[str]
    use_ssl: bool = False
    ssl_cert_path: str | None = None
    username: str | None = None
    password: str | None = None
    api_key: str | None = None
    timeout: float = 60.0
    index_suffix: str | None = None
    monthly_index: bool = True
    number_of_shards: int = 1
    number_of_replicas: int = 0
