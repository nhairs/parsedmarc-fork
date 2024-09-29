"""A Python package for parsing DMARC reports"""

# Future
from __future__ import annotations

# Standard Library
from csv import DictWriter
from datetime import datetime
from io import BytesIO, StringIO
import itertools
import json
import mailbox
import os
import shutil
import tempfile
from typing import Any, BinaryIO, Callable

# Installed
from mailsuite.smtp import send_email

# Package
from parsedmarc.log import logger
from parsedmarc.mail import MailboxConnection
from parsedmarc.parser import (  # noqa: F401
    InvalidAggregateReport,
    InvalidDMARCReport,
    InvalidForensicReport,
    ParserError,
    ReportParser,
)
from parsedmarc.report import (
    AggregateReport,
    ForensicReport,
    Report,
    SortedReportContainer,
)

__version__ = "9.0.0.dev1"

logger.debug(f"parsedmarc v{__version__}")


def _parse_report_record(
    record: dict,
    ip_db_path: str | None = None,
    offline: bool = False,
    nameservers: list[str] | None = None,
    dns_timeout: float = 2.0,
) -> dict:
    """Convert a record from a DMARC aggregate report into a more consistent format

    Args:
        record: The record to convert

    Returns:
        The converted record
    """
    parser = ReportParser(
        offline=offline,
        ip_db_path=ip_db_path,
        nameservers=nameservers,
        dns_timeout=dns_timeout,
    )
    return parser._parse_aggregate_report_record(record)  # pylint: disable=protected-access


def parse_aggregate_report_xml(
    xml: str,
    ip_db_path: str | None = None,
    offline: bool = False,
    nameservers: list[str] | None = None,
    timeout: float = 2.0,
    keep_alive: Callable | None = None,
) -> AggregateReport:
    """Parses a DMARC XML report string and returns an AggregateReport

    Args:
        xml: A string of DMARC aggregate report XML
        ip_db_path: Path to a MMDB file from MaxMind or DBIP
        offline: Do not query online for geolocation or DNS
        nameservers: A list of one or more nameservers to use (Cloudflare's public DNS resolvers by default)
        timeout: Sets the DNS timeout in seconds
        keep_alive: Keep alive function

    Returns:
        The parsed aggregate DMARC report
    """
    parser = ReportParser(
        offline=offline,
        ip_db_path=ip_db_path,
        nameservers=nameservers,
        dns_timeout=timeout,
    )
    return parser.parse_aggregate_report_xml(xml, keep_alive)


def parse_aggregate_report_file(
    source: bytes | str | BinaryIO,
    offline: bool = False,
    ip_db_path: str | None = None,
    nameservers: list[str] | None = None,
    dns_timeout: float = 2.0,
    keep_alive: Callable | None = None,
) -> AggregateReport:
    """Parse a file at the given path, a file-like object. or bytes as an aggregate DMARC report

    Args:
        source: A path to a file, a file like object, or bytes
        offline: Do not query online for geolocation or DNS
        ip_db_path: Path to a MMDB file from MaxMind or DBIP
        nameservers: A list of one or more nameservers to use
            (Cloudflare's public DNS resolvers by default)
        dns_timeout: Sets the DNS timeout in seconds
        keep_alive: Keep alive function

    Returns:
        The parsed DMARC aggregate report
    """
    parser = ReportParser(
        offline=offline,
        ip_db_path=ip_db_path,
        nameservers=nameservers,
        dns_timeout=dns_timeout,
    )
    return parser.parse_aggregate_report_file(source, keep_alive)


def parsed_aggregate_reports_to_csv_rows(
    reports: AggregateReport | list[AggregateReport],
) -> list[dict[str, str | int | bool]]:
    """Convert one or more parsed aggregate reports to list of dicts in flat CSV format

    Args:
        reports: A parsed aggregate report or list of parsed aggregate reports

    Returns:
        Parsed aggregate report data as a list of dicts in flat CSV format
    """

    if isinstance(reports, AggregateReport):
        reports = [reports]

    rows = list(itertools.chain.from_iterable(report.to_csv_rows() for report in reports))

    for r in rows:
        for k, v in r.items():
            if type(v) not in [str, int, bool]:
                r[k] = ""

    return rows


def parsed_aggregate_reports_to_csv(reports: AggregateReport | list[AggregateReport]) -> str:
    """Convert one or more parsed aggregate reports to flat CSV format, including headers

    Args:
        reports: A parsed aggregate report or list of parsed aggregate reports

    Returns:
        Parsed aggregate report data in flat CSV format, including headers
    """
    csv_file = StringIO()
    csv_writer = DictWriter(csv_file, fieldnames=AggregateReport.CSV_FIELDS)
    csv_writer.writeheader()
    csv_writer.writerows(parsed_aggregate_reports_to_csv_rows(reports))
    return csv_file.getvalue()


def parse_forensic_report(
    feedback_report: str,
    sample: str,
    msg_date: datetime,
    offline: bool = False,
    ip_db_path: str | None = None,
    nameservers: list[str] | None = None,
    dns_timeout: float = 2.0,
    strip_attachment_payloads: bool = False,
) -> ForensicReport:
    """Converts a DMARC forensic report and sample to a ForensicReport

    Args:
        feedback_report: A message's feedback report as a string
        sample: The RFC 822 headers or RFC 822 message sample
        msg_date: The message's date header
        offline: Do not query online for geolocation or DNS
        ip_db_path: Path to a MMDB file from MaxMind or DBIP
        nameservers (list): A list of one or more nameservers to use (Cloudflare's public DNS resolvers by default)
        dns_timeout: Sets the DNS timeout in seconds
        strip_attachment_payloads: Remove attachment payloads from forensic report results

    Returns:
        A parsed report and sample
    """
    parser = ReportParser(
        offline=offline,
        ip_db_path=ip_db_path,
        nameservers=nameservers,
        dns_timeout=dns_timeout,
        strip_attachment_payloads=strip_attachment_payloads,
    )
    return parser.parse_forensic_report(feedback_report, sample, msg_date)


def parsed_forensic_reports_to_csv_rows(
    reports: ForensicReport | list[ForensicReport],
) -> list[dict[str, Any]]:
    """Convert one or more parsed forensic reports to a list of dicts in flat CSV format

    Args:
        reports: A parsed forensic report or list of parsed forensic reports

    Returns:
        Parsed forensic report data as a list of dicts in flat CSV format
    """
    if isinstance(reports, ForensicReport):
        reports = [reports]

    return [report.to_csv_row() for report in reports]


def parsed_forensic_reports_to_csv(reports: ForensicReport | list[ForensicReport]) -> str:
    """Convert one or more parsed forensic reports to flat CSV format, including headers

    Args:
        reports: A parsed forensic report or list of parsed forensic reports

    Returns:
        Parsed forensic report data in flat CSV format, including headers
    """
    csv_file = StringIO()
    csv_writer = DictWriter(csv_file, fieldnames=ForensicReport.CSV_FIELDS)
    csv_writer.writeheader()
    csv_writer.writerows(parsed_forensic_reports_to_csv_rows(reports))
    return csv_file.getvalue()


def parse_report_email(
    source: bytes | str,
    offline: bool = False,
    ip_db_path: str | None = None,
    nameservers: list[str] | None = None,
    dns_timeout: float = 2.0,
    strip_attachment_payloads: bool = False,
    keep_alive: Callable | None = None,
) -> Report:
    """Parse a DMARC report from an email

    Args:
        source: An emailed DMARC report in RFC 822 format, as bytes or a string
        offline: Do not query online for geolocation on DNS
        ip_db_path: Path to a MMDB file from MaxMind or DBIP
        nameservers: A list of one or more nameservers to use
        dns_timeout: Sets the DNS timeout in seconds
        strip_attachment_payloads: Remove attachment payloads from forensic report results
        keep_alive: keep alive function

    Returns:
        report container
    """
    parser = ReportParser(
        offline=offline,
        ip_db_path=ip_db_path,
        nameservers=nameservers,
        dns_timeout=dns_timeout,
        strip_attachment_payloads=strip_attachment_payloads,
    )
    return parser.parse_report_email(source, keep_alive)


def parse_report_file(
    source: str | bytes | BinaryIO,
    nameservers: list[str] | None = None,
    dns_timeout: float = 2.0,
    strip_attachment_payloads: bool = False,
    ip_db_path: str | None = None,
    offline: bool = False,
    keep_alive: Callable | None = None,
) -> Report:
    """Parse a DMARC aggregate or forensic file at the given path, a file-like object. or bytes

    Args:
        source: A path to a file, a file like object, or bytes
        nameservers: A list of one or more nameservers to use (Cloudflare's public DNS resolvers by default)
        dns_timeout: Sets the DNS timeout in seconds
        strip_attachment_payloads: Remove attachment payloads from forensic report results
        ip_db_path: Path to a MMDB file from MaxMind or DBIP
        offline: Do not make online queries for geolocation or DNS
        keep_alive: Keep alive function

    Returns:
        The parsed DMARC report
    """
    parser = ReportParser(
        offline=offline,
        ip_db_path=ip_db_path,
        nameservers=nameservers,
        dns_timeout=dns_timeout,
        strip_attachment_payloads=strip_attachment_payloads,
    )
    return parser.parse_report_file(source, keep_alive)


def get_dmarc_reports_from_mbox(
    source: str,
    nameservers: list[str] | None = None,
    dns_timeout: float = 2.0,
    strip_attachment_payloads: bool = False,
    ip_db_path: str | None = None,
    offline: bool = False,
) -> SortedReportContainer:
    """Parses a mailbox in mbox format containing e-mails with attached DMARC reports

    Args:
        source: A path to a mbox file
        nameservers: A list of one or more nameservers to use (Cloudflare's public DNS resolvers by default)
        dns_timeout: Sets the DNS timeout in seconds
        strip_attachment_payloads: Remove attachment payloads from forensic report results
        ip_db_path: Path to a MMDB file from MaxMind or DBIP
        offline: Do not make online queries for geolocation or DNS

    Returns:
        container of reports
    """
    parser = ReportParser(
        offline=offline,
        ip_db_path=ip_db_path,
        nameservers=nameservers,
        dns_timeout=dns_timeout,
        strip_attachment_payloads=strip_attachment_payloads,
    )
    reports = SortedReportContainer()
    try:
        mbox = mailbox.mbox(source)
        message_keys = mbox.keys()
        total_messages = len(message_keys)
        logger.debug(f"Found {total_messages} messages in {source}")
        for i, message_key in enumerate(message_keys):
            logger.info(f"Processing message {i+1} of {total_messages}")
            msg_content = mbox.get_string(message_key)
            try:
                parsed_email = parser.parse_report_email(msg_content)
                reports.add_report(parsed_email)
            except InvalidDMARCReport as error:
                logger.warning(repr(error))
    except mailbox.NoSuchMailboxError as e:
        raise InvalidDMARCReport(f"Mailbox {source} does not exist") from e
    return reports


def get_dmarc_reports_from_mailbox(  # pylint: disable=too-many-positional-arguments
    connection: MailboxConnection,
    reports_folder: str = "INBOX",
    archive_folder: str = "Archive",
    delete: bool = False,
    test: bool = False,
    ip_db_path: str | None = None,
    offline: bool = False,
    nameservers: list[str] | None = None,
    dns_timeout: float = 6.0,
    strip_attachment_payloads: bool = False,
    results: SortedReportContainer | None = None,
    batch_size: int = 10,
    create_folders: bool = True,
) -> SortedReportContainer:
    """Fetches and parses DMARC reports from a mailbox

    Args:
        connection: A Mailbox connection object
        reports_folder: The folder where reports can be found
        archive_folder: The folder to move processed mail to
        delete: Delete  messages after processing them
        test: Do not move or delete messages after processing them
        ip_db_path: Path to a MMDB file from MaxMind or DBIP
        offline: Do not query online for geolocation or DNS
        nameservers: A list of DNS nameservers to query
        dns_timeout: Set the DNS query timeout
        strip_attachment_payloads: Remove attachment payloads from forensic report results
        results: Results from the previous run
        batch_size: Number of messages to read and process before saving (use 0 for no limit)
        create_folders: Whether to create the destination folders (not used in watch)

    Returns:
        collected reported
    """
    if delete and test:
        raise ValueError("delete and test options are mutually exclusive")

    if connection is None:
        raise ValueError("Must supply a connection")

    parser = ReportParser(
        offline=offline,
        ip_db_path=ip_db_path,
        nameservers=nameservers,
        dns_timeout=dns_timeout,
        strip_attachment_payloads=strip_attachment_payloads,
    )
    aggregate_report_msg_uids = []
    forensic_report_msg_uids = []
    aggregate_reports_folder = f"{archive_folder}/Aggregate"
    forensic_reports_folder = f"{archive_folder}/Forensic"
    invalid_reports_folder = f"{archive_folder}/Invalid"

    if not results:
        results = SortedReportContainer()

    if not test and create_folders:
        connection.create_folder(archive_folder)
        connection.create_folder(aggregate_reports_folder)
        connection.create_folder(forensic_reports_folder)
        connection.create_folder(invalid_reports_folder)

    messages = connection.fetch_messages(reports_folder, batch_size=batch_size)
    total_messages = len(messages)
    logger.debug(f"Found {len(messages)} messages in {reports_folder}")

    if batch_size:
        message_limit = min(total_messages, batch_size)
    else:
        message_limit = total_messages

    logger.debug(f"Processing {message_limit} messages")

    for i in range(message_limit):
        msg_uid = messages[i]
        logger.debug(f"Processing message {i+1} of {message_limit}: UID {msg_uid}")
        msg_content = connection.fetch_message(msg_uid)
        try:
            parsed_email = parser.parse_report_email(
                msg_content,
                keep_alive=connection.keepalive,
            )
            parsed_report_type = results.add_report(parsed_email)
            if parsed_report_type == "aggregate":
                aggregate_report_msg_uids.append(msg_uid)
            elif parsed_report_type == "forensic":
                forensic_report_msg_uids.append(msg_uid)

        except InvalidDMARCReport as error:
            logger.warning(repr(error))
            if not test:
                if delete:
                    logger.debug(f"Deleting message UID {msg_uid}")
                    connection.delete_message(msg_uid)
                else:
                    logger.debug(f"Moving message UID {msg_uid} to {invalid_reports_folder}")
                    connection.move_message(msg_uid, invalid_reports_folder)

    if not test:
        if delete:
            processed_messages = aggregate_report_msg_uids + forensic_report_msg_uids

            number_of_processed_msgs = len(processed_messages)
            for i in range(number_of_processed_msgs):
                msg_uid = processed_messages[i]
                logger.debug(f"Deleting message {i+1} of {number_of_processed_msgs}: UID {msg_uid}")
                try:
                    connection.delete_message(msg_uid)

                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error(f"Mailbox error: Error deleting message UID {msg_uid}: {e!r}")
        else:
            if len(aggregate_report_msg_uids) > 0:
                logger.debug(
                    f"Moving aggregate report messages from {reports_folder} to {aggregate_reports_folder}"
                )
                number_of_agg_report_msgs = len(aggregate_report_msg_uids)
                for i in range(number_of_agg_report_msgs):
                    msg_uid = aggregate_report_msg_uids[i]
                    logger.debug(
                        f"Moving message {i+1} of {number_of_agg_report_msgs}: UID {msg_uid}"
                    )
                    try:
                        connection.move_message(msg_uid, aggregate_reports_folder)
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.error(f"Mailbox error: Error moving message UID {msg_uid}: {e!r}")
            if len(forensic_report_msg_uids) > 0:
                logger.debug(
                    f"Moving forensic report messages from {reports_folder} to {forensic_reports_folder}"
                )
                number_of_forensic_msgs = len(forensic_report_msg_uids)
                for i in range(number_of_forensic_msgs):
                    msg_uid = forensic_report_msg_uids[i]
                    logger.debug(
                        f"Moving message {i+1} of {number_of_forensic_msgs}: UID {msg_uid}"
                    )
                    try:
                        connection.move_message(msg_uid, forensic_reports_folder)
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.error(f"Mailbox error: Error moving message UID {msg_uid}: {e!r}")

    total_messages = len(connection.fetch_messages(reports_folder))

    if not test and not batch_size and total_messages > 0:
        # Process emails that came in during the last run
        results = get_dmarc_reports_from_mailbox(
            connection=connection,
            reports_folder=reports_folder,
            archive_folder=archive_folder,
            delete=delete,
            test=test,
            nameservers=nameservers,
            dns_timeout=dns_timeout,
            strip_attachment_payloads=strip_attachment_payloads,
            results=results,
            ip_db_path=ip_db_path,
            offline=offline,
        )

    return results


def watch_inbox(  # pylint: disable=too-many-positional-arguments
    mailbox_connection: MailboxConnection,
    callback: Callable,
    reports_folder: str = "INBOX",
    archive_folder: str = "Archive",
    delete: bool = False,
    test: bool = False,
    check_timeout: int = 30,
    ip_db_path: str | None = None,
    offline: bool = False,
    nameservers: list[str] | None = None,
    dns_timeout: float = 6.0,
    strip_attachment_payloads: bool = False,
    batch_size: int | None = None,
) -> None:
    """Watches a mailbox for new messages and sends the results to a callback function

    Args:
        mailbox_connection: The mailbox connection object
        callback: The callback function to receive the parsing results
        reports_folder: The IMAP folder where reports can be found
        archive_folder: The folder to move processed mail to
        delete: Delete  messages after processing them
        test: Do not move or delete messages after processing them
        check_timeout: Number of seconds to wait for a IMAP IDLE response or the next mail check
        ip_db_path: Path to a MMDB file from MaxMind or DBIP
        offline: Do not query online for geolocation or DNS
        nameservers: A list of one or more nameservers to use (Cloudflare's public DNS resolvers by default)
        dns_timeout: Set the DNS query timeout
        strip_attachment_payloads: Replace attachment payloads in forensic report samples with None
        batch_size: Number of messages to read and process before saving
    """

    def check_callback(connection):
        res = get_dmarc_reports_from_mailbox(
            connection=connection,
            reports_folder=reports_folder,
            archive_folder=archive_folder,
            delete=delete,
            test=test,
            ip_db_path=ip_db_path,
            offline=offline,
            nameservers=nameservers,
            dns_timeout=dns_timeout,
            strip_attachment_payloads=strip_attachment_payloads,
            batch_size=batch_size,
            create_folders=False,
        )
        callback(res)

    mailbox_connection.watch(check_callback=check_callback, check_timeout=check_timeout)
    return


def append_json(filename: str, reports: list[AggregateReport] | list[ForensicReport]) -> None:
    with open(filename, "a+", newline="\n", encoding="utf-8") as output:
        output_json = json.dumps([report.data for report in reports], ensure_ascii=False, indent=2)
        if output.seek(0, os.SEEK_END) != 0:
            if len(reports) == 0:
                # not appending anything, don't do any dance to append it
                # correctly
                return
            output.seek(output.tell() - 1)
            last_char = output.read(1)
            if last_char == "]":
                # remove the trailing "\n]", leading "[\n", and replace with
                # ",\n"
                output.seek(output.tell() - 2)
                output.write(",\n")
                output_json = output_json[2:]
            else:
                output.seek(0)
                output.truncate()

        output.write(output_json)
    return


def append_csv(filename: str, csv: str) -> None:
    with open(filename, "a+", newline="\n", encoding="utf-8") as output:
        if output.seek(0, os.SEEK_END) != 0:
            # strip the headers from the CSV
            _headers, csv = csv.split("\n", 1)
            if len(csv) == 0:
                # not appending anything, don't do any dance to
                # append it correctly
                return
        output.write(csv)
    return


def save_output(
    results: SortedReportContainer,
    output_directory: str = "output",
    aggregate_json_filename: str = "aggregate.json",
    forensic_json_filename: str = "forensic.json",
    aggregate_csv_filename: str = "aggregate.csv",
    forensic_csv_filename: str = "forensic.csv",
) -> None:
    """Save report data in the given directory

    Args:
        results: Parsing results
        output_directory: The path to the directory to save in
        aggregate_json_filename: Filename for the aggregate JSON file
        forensic_json_filename: Filename for the forensic JSON file
        aggregate_csv_filename: Filename for the aggregate CSV file
        forensic_csv_filename: Filename for the forensic CSV file
    """

    if os.path.exists(output_directory):
        if not os.path.isdir(output_directory):
            raise ValueError(f"{output_directory} is not a directory")
    else:
        os.makedirs(output_directory)

    # Save aggregate reports
    append_json(os.path.join(output_directory, aggregate_json_filename), results.aggregate_reports)

    append_csv(
        os.path.join(output_directory, aggregate_csv_filename),
        parsed_aggregate_reports_to_csv(results.aggregate_reports),
    )

    # Save forensic reports
    append_json(os.path.join(output_directory, forensic_json_filename), results.forensic_reports)

    append_csv(
        os.path.join(output_directory, forensic_csv_filename),
        parsed_forensic_reports_to_csv(results.forensic_reports),
    )

    # save sample emails (from forensic reports)
    samples_directory = os.path.join(output_directory, "samples")
    if not os.path.exists(samples_directory):
        os.makedirs(samples_directory)

    sample_filenames = []
    for _forensic_report in results.forensic_reports:
        forensic_report = _forensic_report.data
        sample = forensic_report["sample"]
        message_count = 0
        parsed_sample = forensic_report["parsed_sample"]
        subject = parsed_sample["filename_safe_subject"]
        filename = subject

        while filename in sample_filenames:
            message_count += 1
            filename = f"{subject} ({message_count})"

        sample_filenames.append(filename)

        filename = f"{filename}.eml"
        path = os.path.join(samples_directory, filename)
        with open(path, "w", newline="\n", encoding="utf-8") as sample_file:
            sample_file.write(sample)
    return


def get_report_zip(results: SortedReportContainer) -> bytes:
    """Creates a zip file of parsed report output

    Args:
        results: The parsed results

    Returns:
        raw zip file
    """
    tmp_dir = tempfile.mkdtemp()
    tmp_dir_zip = tempfile.mkdtemp()
    try:
        save_output(results, tmp_dir)
        # https://stackoverflow.com/a/25650295/12281814
        shutil.make_archive(os.path.join(tmp_dir_zip, "archive"), "zip", tmp_dir)
        with open(os.path.join(tmp_dir_zip, "archive.zip"), "rb") as f:
            data = f.read()
    finally:
        shutil.rmtree(tmp_dir)
        shutil.rmtree(tmp_dir_zip)

    return data


def email_results(  # pylint: disable=too-many-positional-arguments
    results: SortedReportContainer,
    host: str,
    mail_from: str,
    mail_to: list[str],
    mail_cc: list[str] | None = None,
    mail_bcc: list[str] | None = None,
    port: int = 0,
    require_encryption: bool = False,
    verify: bool = True,
    username: str | None = None,
    password: str | None = None,
    subject: str | None = None,
    attachment_filename: str | None = None,
    message: str | None = None,
) -> None:
    """Emails parsing results as a zip file

    Args:
        results: Parsing results
        host: Mail server hostname or IP address
        mail_from: The value of the message from header
        mail_to: A list of addresses to mail to
        mail_cc: A list of addresses to CC
        mail_bcc: A list addresses to BCC
        port: Port to use
        require_encryption: Require a secure connection from the start
        verify: verify the SSL/TLS certificate
        username: An optional username
        password: An optional password
        subject: Overrides the default message subject
        attachment_filename: Override the default attachment filename
        message: Override the default plain text body
    """
    logger.debug(f"Emailing report to: {''.join(mail_to)}")
    date_string = datetime.now().strftime("%Y-%m-%d")
    if attachment_filename:
        if not attachment_filename.lower().endswith(".zip"):
            attachment_filename += ".zip"
        filename = attachment_filename
    else:
        filename = f"DMARC-{date_string}.zip"

    assert isinstance(mail_to, list)

    if subject is None:
        subject = f"DMARC results for {date_string}"
    if message is None:
        message = f"DMARC results for {date_string}"
    zip_bytes = get_report_zip(results)
    attachments = [(filename, zip_bytes)]

    send_email(
        host,
        mail_from,
        mail_to,
        message_cc=mail_cc,
        message_bcc=mail_bcc,
        port=port,
        require_encryption=require_encryption,
        verify=verify,
        username=username,
        password=password,
        subject=subject,
        attachments=attachments,
        plain_message=message,
    )
    return None
