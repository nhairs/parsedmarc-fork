### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
import json
import logging
import logging.handlers

# Local
from ..const import AppState
from ..report import AggregateReport, ForensicReport
from .base import BaseConfig, Sink


### CLASSES
### ============================================================================
class Syslog(Sink):
    """Send reports to a syslog server

    Uses [`logging.handlers.SyslogHandler`](https://docs.python.org/3/library/logging.handlers.html#sysloghandler) under the hood.

    *New in 9.0*.
    """

    config: SyslogConfig

    def setup(self) -> None:
        if self._state != AppState.SHUTDOWN:
            raise RuntimeError("Sink is already running")
        self._state = AppState.SETTING_UP

        try:
            self.syslog = logging.getLogger("parsedmarc_syslog")
            self.syslog.setLevel(logging.INFO)
            self._handler = logging.handlers.SysLogHandler(
                address=(self.config.syslog_host, self.config.syslog_port)
            )
            self.syslog.addHandler(self._handler)

        except:
            self._state = AppState.SETUP_ERROR
            raise

        self._state = AppState.RUNNING
        return

    def process_aggregate_report(self, report: AggregateReport) -> None:
        for row in report.to_csv_rows():
            self.syslog.info(json.dumps(row))
        return

    def process_forensic_report(self, report: ForensicReport) -> None:
        self.syslog.info(json.dumps(report.to_csv_row()))
        return


class SyslogConfig(BaseConfig):
    """Syslog Config"""

    syslog_host: str
    syslog_port: int
