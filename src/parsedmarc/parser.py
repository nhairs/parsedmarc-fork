### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
from base64 import b64decode
import binascii
from datetime import datetime
import email
import email.utils
from io import BytesIO
import json
import re
from typing import Any, BinaryIO, Callable, cast
from xml.parsers import expat

# Installed
from expiringdict import ExpiringDict
from lxml import etree
import mailparser
import xmltodict

# Package
from parsedmarc import const
from parsedmarc.log import logger
from parsedmarc.report import AggregateReport, ForensicReport, Report
from parsedmarc.utils import (
    convert_outlook_msg,
    extract_xml,
    get_base_domain,
    get_ip_address_info,
    human_timestamp_to_datetime,
    is_outlook_msg,
    load_bytes_from_source,
    parse_email,
    timestamp_to_human,
)

### CONSTANTS
### ============================================================================
FEEDBACK_REPORT_REGEX = re.compile(r"^([\w\-]+): (.+)$", re.MULTILINE)
XML_HEADER_REGEX = re.compile(r"^<\?xml .*?>", re.MULTILINE)
XML_SCHEMA_REGEX = re.compile(r"</??xs:schema.*>", re.MULTILINE)
TEXT_REPORT_REGEX = re.compile(r"\s*([a-zA-Z\s]+):\s(.+)", re.MULTILINE)


### CLASSES
### ============================================================================
## Exceptions
## -----------------------------------------------------------------------------
class ParserError(RuntimeError):
    """Raised whenever the parser fails for some reason"""


class InvalidDMARCReport(ParserError):
    """Raised when an invalid DMARC report is encountered"""


class InvalidAggregateReport(InvalidDMARCReport):
    """Raised when an invalid DMARC aggregate report is encountered"""


class InvalidForensicReport(InvalidDMARCReport):
    """Raised when an invalid DMARC forensic report is encountered"""


## Parser
## -----------------------------------------------------------------------------
class ReportParser:
    """Report Parser

    Parses reports from messages and files.

    Can handled the following types of reports:

    - DMARC
      - Aggregate
      - Forensic

    *New in 9.0*.
    """

    def __init__(
        self,
        offline: bool = False,
        ip_db_path: str | None = None,
        nameservers: list[str] | None = None,
        dns_timeout: float = 2.0,
        strip_attachment_payloads: bool = False,
    ) -> None:
        """Args:
        offline:
        ip_db_path:
        nameservers:
        dns_timeout:
        strip_attachment_payloads: Remove attachment payloads from forensic report results
        """
        self.offline = offline
        self.ip_db_path = ip_db_path
        self.nameservers = nameservers
        self.dns_timeout = dns_timeout
        self.strip_attachment_payloads = strip_attachment_payloads
        self._ip_address_cache = ExpiringDict(max_len=10000, max_age_seconds=1800)
        return

    ## Generic Parsing Methods
    ## -------------------------------------------------------------------------
    def parse_report_email(
        self,
        source: bytes | str,
        keep_alive: Callable | None = None,
    ) -> Report:
        """Parse a DMARC report from an email

        Args:
            source: An emailed DMARC report in RFC 822 format, as bytes or a string
            keep_alive: keep alive function

        Returns:
            the report parsed from the email
        """
        try:
            if isinstance(source, bytes) and is_outlook_msg(source):
                source = convert_outlook_msg(source)
            if isinstance(source, bytes):
                source = source.decode(encoding="utf8", errors="replace")
            msg = mailparser.parse_from_string(source)
            msg_headers = json.loads(msg.headers_json)
            if "Date" in msg_headers:
                date = human_timestamp_to_datetime(msg_headers["Date"])
            else:
                date = datetime.utcnow()
            msg = email.message_from_string(source)

        except Exception as e:
            raise InvalidDMARCReport(repr(e)) from e
        subject = None
        feedback_report = None
        sample = None
        if "From" in msg_headers:
            logger.info(f"Parsing mail from {msg_headers['From']}")
        if "Subject" in msg_headers:
            subject = msg_headers["Subject"]
        for part in msg.walk():
            content_type = part.get_content_type()
            payload = part.get_payload()
            if not isinstance(payload, list):
                payload = [payload]
            payload = str(payload[0])
            if content_type == "message/feedback-report":
                try:
                    if "Feedback-Type" in payload:
                        feedback_report = payload
                    else:
                        feedback_report = str(b64decode(payload))
                    feedback_report = feedback_report.lstrip("b'").rstrip("'")
                    feedback_report = feedback_report.replace("\\r", "")
                    feedback_report = feedback_report.replace("\\n", "\n")
                except (ValueError, TypeError, binascii.Error):
                    feedback_report = payload

            elif content_type == "text/rfc822-headers":
                sample = payload
            elif content_type == "message/rfc822":
                sample = payload
            elif content_type == "text/plain":
                if "A message claiming to be from you has failed" in payload:
                    parts = payload.split("detected.")
                    fields = {
                        match[0].lower().replace(" ", "-"): match[1].strip()
                        for match in TEXT_REPORT_REGEX.findall(parts[0])
                    }
                    feedback_report = f"Arrival-Date: {fields['received-date']}\nSource-IP: {fields['sender-ip-address']}"  # noqa: E501
                    sample = parts[1].lstrip().replace("=\r\n", "")
                    logger.debug(sample)
            else:
                try:
                    payload = b64decode(payload)
                    if (
                        payload.startswith(const.MAGIC_ZIP)
                        or payload.startswith(const.MAGIC_GZIP)
                        or payload.startswith(const.MAGIC_XML)
                    ):
                        aggregate_report = self.parse_aggregate_report_file(
                            payload,
                            keep_alive=keep_alive,
                        )
                        return aggregate_report

                except (TypeError, ValueError, binascii.Error):
                    pass

                except InvalidAggregateReport as e:
                    error = f"Message with subject {subject!r} is not a valid aggregate DMARC report: {e!r}"
                    raise InvalidAggregateReport(error) from e

                except Exception as e:
                    error = f"Unable to parse message with subject {subject!r}: {e!r}"
                    raise InvalidDMARCReport(error) from e

        if feedback_report and sample:
            try:
                forensic_report = self.parse_forensic_report(
                    feedback_report,
                    sample,
                    date,
                )
            except InvalidForensicReport as e:
                error = (
                    f"Message with subject {subject!r} is not a valid forensic DMARC report: {e!r}"
                )
                raise InvalidForensicReport(error) from e
            except Exception as e:
                raise InvalidForensicReport(repr(e)) from e

            return forensic_report

        raise InvalidDMARCReport(f"Message with subject {subject!r} is not a valid DMARC report")

    def parse_report_file(
        self,
        source: str | bytes | BinaryIO,
        keep_alive: Callable | None = None,
    ) -> Report:
        """Parse a DMARC aggregate or forensic file at the given path, a file-like object. or bytes

        Args:
            source: A path to a file, a file like object, or bytes
            keep_alive: Keep alive function

        Returns:
            The parsed DMARC report
        """
        if isinstance(source, str):
            logger.debug(f"Parsing {source}")

        content = load_bytes_from_source(source)

        report: Report

        try:
            report = self.parse_aggregate_report_file(content, keep_alive)

        except InvalidAggregateReport:
            try:
                report = self.parse_report_email(
                    content,
                    keep_alive,
                )
            except InvalidDMARCReport:
                # pylint: disable=raise-missing-from
                # We want to overwrite the message here.
                raise InvalidDMARCReport("Not a valid aggregate or forensic report")
        return report

    ## DMARC Aggregate Report Parsing
    ## -------------------------------------------------------------------------
    def parse_aggregate_report_file(
        self,
        source: bytes | str | BinaryIO,
        keep_alive: Callable | None = None,
    ) -> AggregateReport:
        """Parse a file at the given path, a file-like object. or bytes as an aggregate DMARC report

        Args:
            source: A path to a file, a file like object, or bytes
            keep_alive: Keep alive function

        Returns:
            The parsed DMARC aggregate report
        """
        try:
            xml = extract_xml(source)
        except ValueError as e:
            raise InvalidAggregateReport(repr(e)) from e

        return self.parse_aggregate_report_xml(xml, keep_alive=keep_alive)

    def parse_aggregate_report_xml(
        self,
        xml: str,
        keep_alive: Callable | None = None,
    ) -> AggregateReport:
        """Parses a DMARC XML report string and returns an AggregateReport

        Args:
            xml: A string of DMARC aggregate report XML
            keep_alive: Keep alive function

        Returns:
            The parsed aggregate DMARC report
        """
        errors = []
        # Parse XML and recover from errors
        try:
            xmltodict.parse(xml)["feedback"]
        except Exception as e:  # pylint: disable=broad-exception-caught
            errors.append(f"Invalid XML: {e!r}")
            try:
                tree = etree.parse(
                    BytesIO(xml.encode("utf-8")),
                    etree.XMLParser(recover=True, resolve_entities=False),
                )
                s = etree.tostring(tree)
                xml = "" if s is None else s.decode("utf-8")
            except Exception:  # pylint: disable=broad-exception-caught
                xml = "<a/>"

        try:
            # Replace XML header (sometimes they are invalid)
            xml = XML_HEADER_REGEX.sub('<?xml version="1.0"?>', xml)

            # Remove invalid schema tags
            xml = XML_SCHEMA_REGEX.sub("", xml)

            report = xmltodict.parse(xml)["feedback"]
            report_metadata = report["report_metadata"]
            schema = "draft"
            if "version" in report:
                schema = report["version"]
            new_report: dict[str, Any] = {"xml_schema": schema}
            new_report_metadata: dict[str, Any] = {}
            if report_metadata["org_name"] is None:
                if report_metadata["email"] is not None:
                    report_metadata["org_name"] = report_metadata["email"].split("@")[-1]
            org_name = report_metadata["org_name"]
            if org_name is not None and " " not in org_name:
                new_org_name = get_base_domain(org_name)
                if new_org_name is not None:
                    org_name = new_org_name
            if not org_name:
                logger.debug(f"Could not parse org_name from XML.\r\n{report}")
                raise KeyError(
                    "Organization name is missing. This field is a requirement for saving the report"
                )
            new_report_metadata["org_name"] = org_name
            new_report_metadata["org_email"] = report_metadata["email"]
            extra = report_metadata.get("extra_contact_info")
            new_report_metadata["org_extra_contact_info"] = extra
            new_report_metadata["report_id"] = report_metadata["report_id"]
            report_id = new_report_metadata["report_id"]
            report_id = report_id.replace("<", "").replace(">", "").split("@")[0]
            new_report_metadata["report_id"] = report_id
            date_range = report["report_metadata"]["date_range"]
            if int(date_range["end"]) - int(date_range["begin"]) > 2 * 86400:
                errors.append("Timespan > 24 hours - RFC 7489 section 7.2")
            date_range["begin"] = timestamp_to_human(date_range["begin"])
            date_range["end"] = timestamp_to_human(date_range["end"])
            new_report_metadata["begin_date"] = date_range["begin"]
            new_report_metadata["end_date"] = date_range["end"]
            if "error" in report["report_metadata"]:
                if not isinstance(report["report_metadata"]["error"], list):
                    errors = [report["report_metadata"]["error"]]
                else:
                    errors = report["report_metadata"]["error"]
            new_report_metadata["errors"] = errors
            new_report["report_metadata"] = new_report_metadata
            records = []
            policy_published = report["policy_published"]
            new_policy_published = {}
            new_policy_published["domain"] = policy_published["domain"]
            adkim = "r"
            if "adkim" in policy_published:
                if policy_published["adkim"] is not None:
                    adkim = policy_published["adkim"]
            new_policy_published["adkim"] = adkim
            aspf = "r"
            if "aspf" in policy_published:
                if policy_published["aspf"] is not None:
                    aspf = policy_published["aspf"]
            new_policy_published["aspf"] = aspf
            new_policy_published["p"] = policy_published["p"]
            sp = new_policy_published["p"]
            if "sp" in policy_published:
                if policy_published["sp"] is not None:
                    sp = report["policy_published"]["sp"]
            new_policy_published["sp"] = sp
            pct = "100"
            if "pct" in policy_published:
                if policy_published["pct"] is not None:
                    pct = report["policy_published"]["pct"]
            new_policy_published["pct"] = pct
            fo = "0"
            if "fo" in policy_published:
                if policy_published["fo"] is not None:
                    fo = report["policy_published"]["fo"]
            new_policy_published["fo"] = fo
            new_report["policy_published"] = new_policy_published

            if isinstance(report["record"], list):
                record_count = len(report["record"])
                for i in range(record_count):
                    if keep_alive is not None and i > 0 and i % 20 == 0:
                        logger.debug("Sending keepalive cmd")
                        keep_alive()
                        logger.debug(f"Processed {i}/{record_count}")
                    report_record = self._parse_aggregate_report_record(report["record"][i])
                    records.append(report_record)

            else:
                report_record = self._parse_aggregate_report_record(report["record"])
                records.append(report_record)

            new_report["records"] = records

            return AggregateReport(new_report)

        except expat.ExpatError as error:
            raise InvalidAggregateReport(f"Invalid XML: {error!r}") from error

        except KeyError as error:
            raise InvalidAggregateReport(f"Missing field: {error!r}") from error

        except AttributeError as error:
            raise InvalidAggregateReport("Report missing required section") from error

        except Exception as error:
            raise InvalidAggregateReport(f"Unexpected error: {error!r}") from error

    def _parse_aggregate_report_record(self, record: dict) -> dict:
        """Convert a record from a DMARC aggregate report into a more consistent format

        Args:
            record: The record to convert

        Returns:
            The converted record
        """
        record = record.copy()
        new_record: dict[str, Any] = {}
        new_record_source = get_ip_address_info(
            record["row"]["source_ip"],
            cache=self._ip_address_cache,
            ip_db_path=self.ip_db_path,
            offline=self.offline,
            nameservers=self.nameservers,
            timeout=self.dns_timeout,
        )
        new_record["source"] = new_record_source
        new_record["count"] = int(record["row"]["count"])
        policy_evaluated = record["row"]["policy_evaluated"].copy()
        new_policy_evaluated = {
            "disposition": "none",
            "dkim": "fail",
            "spf": "fail",
            "policy_override_reasons": [],
        }
        if "disposition" in policy_evaluated:
            new_policy_evaluated["disposition"] = policy_evaluated["disposition"]
            if cast(str, new_policy_evaluated["disposition"]).strip().lower() == "pass":
                new_policy_evaluated["disposition"] = "none"
        if "dkim" in policy_evaluated:
            new_policy_evaluated["dkim"] = policy_evaluated["dkim"]
        if "spf" in policy_evaluated:
            new_policy_evaluated["spf"] = policy_evaluated["spf"]
        reasons = []
        spf_aligned = (
            policy_evaluated["spf"] is not None and policy_evaluated["spf"].lower() == "pass"
        )
        dkim_aligned = (
            policy_evaluated["dkim"] is not None and policy_evaluated["dkim"].lower() == "pass"
        )
        dmarc_aligned = spf_aligned or dkim_aligned
        new_record["alignment"] = {}
        new_record["alignment"]["spf"] = spf_aligned
        new_record["alignment"]["dkim"] = dkim_aligned
        new_record["alignment"]["dmarc"] = dmarc_aligned
        if "reason" in policy_evaluated:
            if isinstance(policy_evaluated["reason"], list):
                reasons = policy_evaluated["reason"]
            else:
                reasons = [policy_evaluated["reason"]]
        for reason in reasons:
            if "comment" not in reason:
                reason["comment"] = None
        new_policy_evaluated["policy_override_reasons"] = reasons
        new_record["policy_evaluated"] = new_policy_evaluated
        if "identities" in record:
            new_record["identifiers"] = record["identities"].copy()
        else:
            new_record["identifiers"] = record["identifiers"].copy()
        new_record["auth_results"] = {"dkim": [], "spf": []}
        if isinstance(new_record["identifiers"]["header_from"], str):
            lowered_from = new_record["identifiers"]["header_from"].lower()
        else:
            lowered_from = ""
        new_record["identifiers"]["header_from"] = lowered_from

        if isinstance(record["auth_results"], dict):
            auth_results = record["auth_results"].copy()
            if "spf" not in auth_results:
                auth_results["spf"] = []
            if "dkim" not in auth_results:
                auth_results["dkim"] = []
        else:
            auth_results = new_record["auth_results"].copy()

        if not isinstance(auth_results["dkim"], list):
            auth_results["dkim"] = [auth_results["dkim"]]
        for result in auth_results["dkim"]:
            if "domain" in result and result["domain"] is not None:
                new_result = {"domain": result["domain"]}
                if "selector" in result and result["selector"] is not None:
                    new_result["selector"] = result["selector"]
                else:
                    new_result["selector"] = "none"
                if "result" in result and result["result"] is not None:
                    new_result["result"] = result["result"]
                else:
                    new_result["result"] = "none"
                new_record["auth_results"]["dkim"].append(new_result)

        if not isinstance(auth_results["spf"], list):
            auth_results["spf"] = [auth_results["spf"]]
        for result in auth_results["spf"]:
            if "domain" in result and result["domain"] is not None:
                new_result = {"domain": result["domain"]}
                if "scope" in result and result["scope"] is not None:
                    new_result["scope"] = result["scope"]
                else:
                    new_result["scope"] = "mfrom"
                if "result" in result and result["result"] is not None:
                    new_result["result"] = result["result"]
                else:
                    new_result["result"] = "none"
                new_record["auth_results"]["spf"].append(new_result)

        if "envelope_from" not in new_record["identifiers"]:
            envelope_from = None
            if len(auth_results["spf"]) > 0:
                spf_result = auth_results["spf"][-1]
                if "domain" in spf_result:
                    envelope_from = spf_result["domain"]
            if envelope_from is not None:
                envelope_from = str(envelope_from).lower()
            new_record["identifiers"]["envelope_from"] = envelope_from

        elif new_record["identifiers"]["envelope_from"] is None:
            if len(auth_results["spf"]) > 0:
                envelope_from = new_record["auth_results"]["spf"][-1]["domain"]
                if envelope_from is not None:
                    envelope_from = str(envelope_from).lower()
                new_record["identifiers"]["envelope_from"] = envelope_from

        envelope_to = None
        if "envelope_to" in new_record["identifiers"]:
            envelope_to = new_record["identifiers"]["envelope_to"]
            del new_record["identifiers"]["envelope_to"]

        new_record["identifiers"]["envelope_to"] = envelope_to

        return new_record

    ## DMARC Forensic Report Parsing
    ## -------------------------------------------------------------------------
    def parse_forensic_report(
        self,
        feedback_report: str,
        sample: str,
        msg_date: datetime,
    ) -> ForensicReport:
        """Converts a DMARC forensic report and sample to a ForensicReport

        Args:
            feedback_report: A message's feedback report as a string
            sample: The RFC 822 headers or RFC 822 message sample
            msg_date: The message's date header

        Returns:
            A parsed report and sample
        """
        delivery_results = ["delivered", "spam", "policy", "reject", "other"]

        try:
            parsed_report: dict[str, Any] = {}
            report_values = FEEDBACK_REPORT_REGEX.findall(feedback_report)
            for report_value in report_values:
                key = report_value[0].lower().replace("-", "_")
                parsed_report[key] = report_value[1]

            if "arrival_date" not in parsed_report:
                if msg_date is None:
                    raise InvalidForensicReport("Forensic sample is not a valid email")
                parsed_report["arrival_date"] = msg_date.isoformat()

            if "version" not in parsed_report:
                parsed_report["version"] = None

            if "user_agent" not in parsed_report:
                parsed_report["user_agent"] = None

            if "delivery_result" not in parsed_report:
                parsed_report["delivery_result"] = None
            else:
                for delivery_result in delivery_results:
                    if delivery_result in parsed_report["delivery_result"].lower():
                        parsed_report["delivery_result"] = delivery_result
                        break
            if parsed_report["delivery_result"] not in delivery_results:
                parsed_report["delivery_result"] = "other"

            parsed_report["arrival_date_utc"] = human_timestamp_to_datetime(
                parsed_report["arrival_date"], to_utc=True
            ).strftime("%Y-%m-%d %H:%M:%S")

            ip_address = re.split(r"\s", parsed_report["source_ip"]).pop(0)
            parsed_report_source = get_ip_address_info(
                ip_address,
                cache=self._ip_address_cache,
                ip_db_path=self.ip_db_path,
                offline=self.offline,
                nameservers=self.nameservers,
                timeout=self.dns_timeout,
            )
            parsed_report["source"] = parsed_report_source
            del parsed_report["source_ip"]

            if "identity_alignment" not in parsed_report:
                parsed_report["authentication_mechanisms"] = []
            elif parsed_report["identity_alignment"] == "none":
                parsed_report["authentication_mechanisms"] = []
                del parsed_report["identity_alignment"]
            else:
                auth_mechanisms = parsed_report["identity_alignment"]
                auth_mechanisms = auth_mechanisms.split(",")
                parsed_report["authentication_mechanisms"] = auth_mechanisms
                del parsed_report["identity_alignment"]

            if "auth_failure" not in parsed_report:
                parsed_report["auth_failure"] = "dmarc"
            auth_failure = parsed_report["auth_failure"].split(",")
            parsed_report["auth_failure"] = auth_failure

            optional_fields = [
                "original_envelope_id",
                "dkim_domain",
                "original_mail_from",
                "original_rcpt_to",
            ]
            for optional_field in optional_fields:
                if optional_field not in parsed_report:
                    parsed_report[optional_field] = None

            parsed_sample = parse_email(sample, self.strip_attachment_payloads)

            if "reported_domain" not in parsed_report:
                parsed_report["reported_domain"] = parsed_sample["from"]["domain"]

            sample_headers_only = False
            number_of_attachments = len(parsed_sample["attachments"])
            if number_of_attachments < 1 and parsed_sample["body"] is None:
                sample_headers_only = True
            if sample_headers_only and parsed_sample["has_defects"]:
                del parsed_sample["defects"]
                del parsed_sample["defects_categories"]
                del parsed_sample["has_defects"]
            parsed_report["sample_headers_only"] = sample_headers_only
            parsed_report["sample"] = sample
            parsed_report["parsed_sample"] = parsed_sample

            return ForensicReport(parsed_report)

        except KeyError as error:
            raise InvalidForensicReport(f"Missing value: {error!r}") from error

        except Exception as error:
            raise InvalidForensicReport(f"Unexpected error: {error!r}") from error
