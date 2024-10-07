### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
import json
from typing import Any, Literal

# Installed
import boto3.session
from pydantic import BaseModel

# Local
from ..const import AppState
from ..report import AggregateReport, ForensicReport
from ..utils import human_timestamp_to_datetime
from .base import BaseConfig, Sink


### CLASSES
### ============================================================================
class AwsBase(Sink):
    """Base class for sinks using AWS"""

    config: AwsConfig
    session: boto3.session.Session

    def _set_session(self) -> boto3.session.Session:
        if hasattr(self, "session"):
            # Do not overwrite session
            return self.session

        session = boto3.session.Session(
            aws_access_key_id=self.config.client.aws_access_key_id,
            aws_secret_access_key=self.config.client.aws_secret_access_key,
            aws_session_token=self.config.client.aws_session_token,
            region_name=self.config.client.region_name,
            profile_name=self.config.client.profile_name,
        )
        self.session = session
        return session

    # Mypy doesn't like this code because client_name isn't a literal so it doesn't
    # know how to select which overload. So instead it's left as boilerplate for
    # classes to use directly in their own self.setup methods.
    # This code also works for session.resoure(...)
    #
    # def _get_client(self, client_name: str):
    #     client = self._set_session().client(
    #         client_name,
    #         api_version=self.config.client.api_version,
    #         use_ssl=self.config.client.use_ssl,
    #         verify=self.config.client.verify,
    #         endpoint_url=self.config.client.endpoint_url,
    #     )
    #     return client


class AwsConfig(BaseConfig):
    client: AwsClientConfig


class AwsClientConfig(BaseModel):
    # Session
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    region_name: str | None = None
    profile_name: str | None = None
    # Client
    api_version: str | None = None
    use_ssl: bool | None = None
    verify: bool | str | None = None
    endpoint_url: str | None = None


## S3
## -----------------------------------------------------------------------------
class S3(AwsBase):
    """Stores reports in AWS S3 as JSON

    *New in 9.0*.
    """

    config: S3Config

    _METADATA_KEYS = [
        "org_name",
        "org_email",
        "report_id",
        "begin_date",
        "end_date",
    ]

    def setup(self) -> None:
        if self._state != AppState.SHUTDOWN:
            raise RuntimeError("Sink is already running")
        self._state = AppState.SETTING_UP

        try:
            self.s3 = self._set_session().resource(
                "s3",
                api_version=self.config.client.api_version,
                use_ssl=self.config.client.use_ssl,
                verify=self.config.client.verify,
                endpoint_url=self.config.client.endpoint_url,
            )
            self.bucket = self.s3.Bucket(self.config.bucket)

        except:
            self._state = AppState.SETUP_ERROR
            raise

        self._state = AppState.RUNNING
        return

    def process_aggregate_report(self, report: AggregateReport) -> None:
        self.save_raw_report(report.data, "aggregate")
        return

    def process_forensic_report(self, report: ForensicReport) -> None:
        self.save_raw_report(report.data, "forensic")
        return

    def save_raw_report(
        self, report: dict[str, Any], report_type: Literal["aggregate", "forensic"]
    ) -> None:
        report_date = human_timestamp_to_datetime(report["report_metadata"]["begin_date"])
        report_id = report["report_metadata"]["report_id"]
        object_path = f"{self.config.path_prefix}/{report_type}/year={report_date.year}/month={report_date.month:02d}/day={report_date.day:02d}/{report_id}.json"

        metadata = {k: v for k, v in report["report_metadata"].items() if k in self._METADATA_KEYS}

        self.logger.debug(f"Saving {report_type} to s3://{self.config.bucket}/{object_path}")

        self.bucket.put_object(Body=json.dumps(report), Key=object_path, Metadata=metadata)
        return


class S3Config(AwsConfig):
    """S3 Config"""

    bucket: str
    path_prefix: str = ""
