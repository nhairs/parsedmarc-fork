### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
from collections import deque
from io import BytesIO
from typing import TYPE_CHECKING, Any, Dict

# Installed
import boto3
import boto3.session
import orjson
from pydantic import Field

if TYPE_CHECKING:
    import mypy_boto3_s3.service_resource as t_s3
    import mypy_boto3_sqs.service_resource as t_sqs

# Local
from ..const import AppState
from ..parser import InvalidDMARCReport
from .base import BaseConfig, Job, JobStatus, Source


### CLASSES
### ============================================================================
class SimpleEmailService(Source):
    """AWS Simple Email Service (SES) Source

    This source allows reading email from SES where emails are stored in S3 and
    notifications of new emails are sent to SQS via SNS.

    References:

    - https://docs.aws.amazon.com/ses/latest/dg/receiving-email.html
    - https://docs.aws.amazon.com/ses/latest/dg/receiving-email-notifications-examples.html

    *New in 9.0*.
    """

    config: SimpleEmailServiceConfig

    def setup(self) -> None:
        if self._state != AppState.SHUTDOWN:
            raise RuntimeError("Source is already running")
        self._state = AppState.SETTING_UP

        try:
            self._session = boto3.session.Session(**self.config.session)
            self._sqs = self._session.resource("sqs")
            self._sqs_queue = self._sqs.Queue(self.config.queue_name)
            self._message_queue: deque[t_sqs.Message] = deque()
            self._s3 = self._session.resource("s3")
        except:
            self._state = AppState.SETUP_ERROR
            raise
        self._state = AppState.RUNNING
        return

    def get_job(self) -> Job | None:
        if self._state != AppState.RUNNING:
            raise RuntimeError("Source is not running")

        if not self._message_queue:
            self.vvdebug("Fetching messages")
            self._message_queue.extend(
                self._sqs_queue.receive_messages(
                    MessageSystemAttributeNames=["All"],
                    MaxNumberOfMessages=10,
                    VisibilityTimeout=300,
                    WaitTimeSeconds=20,
                )
            )

        while self._message_queue:
            message = self._message_queue.popleft()
            self.vdebug(f"Processing message {message.message_id}")
            raw_email = self._download_object(self._get_object_from_message(message)).getvalue()
            try:
                report = self.parser.parse_report_email(raw_email)
                job = Job(
                    source=self,
                    report=report,
                    identifier=message.message_id,
                    data={"message": message},
                )
                self.register_job(job)
                return job

            except InvalidDMARCReport as error:
                self.logger.warning(repr(error))
                self._remove_message(message)
            continue
        return None

    def ack_job(self, job: Job, status: JobStatus) -> None:
        if self._state not in {AppState.RUNNING, AppState.SHUTTING_DOWN}:
            raise RuntimeError("Source is not running")

        if status == JobStatus.SUCCESS:
            # Remove message from queue
            self._remove_message(job.data["message"])

        elif status in {JobStatus.CANCELLED, JobStatus.ERROR}:
            # Return message to queue
            self._return_message(job.data["message"])

        else:
            raise NotImplementedError(f"{self.__class__.__name__} does not support {status=}")

        super().ack_job(job, status)
        return

    def cleanup(self) -> None:
        super().cleanup()
        # Send outstanding messages back to SQS
        while self._message_queue:
            message = self._message_queue.popleft()
            self._return_message(message)
        return

    def _return_message(self, message: t_sqs.Message) -> None:
        """Return a message to the sqs queue

        Args:
            message: the message to return
        """
        self.vdebug(f"Returning message {message.message_id} to SQS")
        message.change_visibility(VisibilityTimeout=0)
        return

    def _remove_message(self, message: t_sqs.Message) -> None:
        """Remove a message and the data in S3

        Args:
            message: the message to delete
        """
        s3_object = self._get_object_from_message(message)
        self.vdebug(f"Deleting s3://{s3_object.bucket_name}{s3_object.key}")
        s3_object.delete()
        self.vdebug(f"Deleting message {message.message_id} from SQS")
        message.delete()
        return

    def _get_object_from_message(self, message: t_sqs.Message) -> t_s3.Object:
        """Get the S3 object referred to in the SQS message

        Args:
            message: the message to parse
        """
        full_data = orjson.loads(orjson.loads(message.body)["Message"])
        action_data = full_data["receipt"]["action"]
        bucket = action_data["bucketName"]
        key = action_data["objectKey"]
        return self._s3.Object(bucket, key)

    def _download_object(self, s3_object: t_s3.Object) -> BytesIO:
        """Downlaod an object from S3"""
        data = BytesIO()
        s3_object.download_fileobj(data)
        data.seek(0)
        return data


class SimpleEmailServiceConfig(BaseConfig):
    """SimpleEmailService Config

    *New in 9.0*.
    """

    session: Dict[str, Any] = Field(default_factory=dict)
    queue_name: str
