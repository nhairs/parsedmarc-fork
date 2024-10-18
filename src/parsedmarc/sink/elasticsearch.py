### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
from typing import List, Literal, Union

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
            self.client = ElasticsearchClient(
                hosts=self.config.client.hosts,
                use_ssl=self.config.client.ssl,
                ssl_cert_path=self.config.client.cert_path,
                username=self.config.client.username,
                password=self.config.client.password,
                api_key=self.config.client.api_key,
                timeout=self.config.client.timeout,
                index_suffix=self.config.index_suffix,
                index_prefix=self.config.index_prefix,
                monthly_indexes=self.config.monthly_indexes,
                number_of_shards=self.config.number_of_shards,
                number_of_replicas=self.config.number_of_replicas,
            )
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
    index_suffix: Union[str, None] = None
    index_prefix: str = ""
    monthly_indexes: bool = True
    number_of_shards: int = 1
    number_of_replicas: int = 0
    on_duplicate: Literal["discard"] = "discard"  # TODO: implement update logic and add


class ElasticsearchClientConfig(BaseModel):
    """Elasticsearch Client Config"""

    hosts: Union[str, List[str]]
    ssl: bool = False
    cert_path: Union[str, None] = None
    username: Union[str, None] = None
    password: Union[str, None] = None
    api_key: Union[str, None] = None
    timeout: float = 60.0
