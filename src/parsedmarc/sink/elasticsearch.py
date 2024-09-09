### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
from typing import Any, Dict, Literal

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
            self.client = ElasticsearchClient(**self.config.client)
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

    # As per https://elasticsearch-py.readthedocs.io/en/v8.13.0/api/elasticsearch.html
    client: Dict[str, Any]
    on_duplicate: Literal["discard"] = "discard"  # TODO: implement update logic and add
