from typing import List, Dict, Optional

from azure.core.exceptions import HttpResponseError
from azure.identity import ClientSecretCredential
from azure.monitor.ingestion import LogsIngestionClient

from parsedmarc.log import logger


class LogAnalyticsException(Exception):
    """Errors originating from LogsIngestionClient"""


class LogAnalyticsClient(object):
    """Azure Log Analytics Client

    Pushes the  DMARC reports to Log Analytics via Data Collection Rules.

    References:
      - https://learn.microsoft.com/en-us/azure/azure-monitor/logs/logs-ingestion-api-overview
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        dce: str,
        dcr_immutable_id: str,
        dcr_aggregate_stream: Optional[str] = None,
        dcr_forensic_stream: Optional[str] = None,
    ):
        """
        Args:
            client_id: The client ID of the service principle.
            client_secret: The client secret of the service principle.
            tenant_id: The tenant ID where the service principle resides.
            dce: The Data Collection Endpoint (DCE) used by the Data Collection Rule (DCR).
            dcr_immutable_id: The immutable ID of the Data Collection Rule (DCR).
            dcr_aggregate_stream: The Stream name where the Aggregate DMARC reports need to be pushed.
            dcr_forensic_stream: The Stream name where the Forensic DMARC reports need to be pushed.
        """
        self.client_id = client_id
        self._client_secret = client_secret
        self.tenant_id = tenant_id
        self.dce = dce
        self.dcr_immutable_id = dcr_immutable_id
        self.dcr_aggregate_stream = dcr_aggregate_stream
        self.dcr_forensic_stream = dcr_forensic_stream

        self._credential = ClientSecretCredential(
            tenant_id=tenant_id, client_id=client_id, client_secret=client_secret
        )
        self.logs_client = LogsIngestionClient(dce, credential=self._credential)
        return

    def _publish_json(self, reports: List[Dict], dcr_stream: str) -> None:
        """Publish DMARC reports to the given Data Collection Rule.

        Args:
            results: The results generated by parsedmarc.
            logs_client: The client used to send the DMARC reports.
            dcr_stream: The stream name where the DMARC reports needs to be pushed.
        """
        try:
            self.logs_client.upload(self.dcr_immutable_id, dcr_stream, reports)  # type: ignore[attr-defined]
        except HttpResponseError as e:
            raise LogAnalyticsException(f"Upload failed: {e!r}")
        return

    def publish_results(
        self, results: Dict[str, List[Dict]], save_aggregate: bool, save_forensic: bool
    ) -> None:
        """Publish DMARC reports to Log Analytics via Data Collection Rules (DCR).

        Args:
            results: The DMARC reports (Aggregate & Forensic)
            save_aggregate: Whether Aggregate reports can be saved into Log Analytics
            save_forensic: Whether Forensic reports can be saved into Log Analytics
        """
        if results["aggregate_reports"] and self.dcr_aggregate_stream and save_aggregate:
            logger.info("Publishing aggregate reports.")
            self._publish_json(results["aggregate_reports"], self.dcr_aggregate_stream)
            logger.info("Successfully pushed aggregate reports.")

        if results["forensic_reports"] and self.dcr_forensic_stream and save_forensic:
            logger.info("Publishing forensic reports.")
            self._publish_json(results["forensic_reports"], self.dcr_forensic_stream)
            logger.info("Successfully pushed forensic reports.")
        return
