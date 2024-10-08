"""Utility functions that might be useful for other projects"""

# Future
from __future__ import annotations

# Standard Library
import atexit
import base64
from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.resources
from io import BytesIO
import json
import logging
import mailbox
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, BinaryIO
import zipfile
import zlib

# Installed
from dateutil.parser import parse as parse_date
import dns.exception
import dns.resolver
import dns.reversename
from expiringdict import ExpiringDict
import geoip2.database
import geoip2.errors
import mailparser
import publicsuffixlist

# Package
from parsedmarc import const
from parsedmarc.log import logger
import parsedmarc.resources.dbip

parenthesis_regex = re.compile(r"\s*\(.*\)\s*")

mailparser_logger = logging.getLogger("mailparser")
mailparser_logger.setLevel(logging.CRITICAL)

tempdir = tempfile.mkdtemp()


def _cleanup():
    """Remove temporary files"""
    shutil.rmtree(tempdir)


atexit.register(_cleanup)


class EmailParserError(RuntimeError):
    """Raised when an error parsing the email occurs"""


class DownloadError(RuntimeError):
    """Raised when an error occurs when downloading a file"""


def decode_base64(data: str) -> bytes:
    """Decodes a base64 string, with padding being optional

    Args:
        data: A base64 encoded string

    Returns:
        The decoded bytes

    """
    data_bytes = bytes(data, encoding="ascii")
    missing_padding = len(data_bytes) % 4
    if missing_padding != 0:
        data_bytes += b"=" * (4 - missing_padding)
    return base64.b64decode(data_bytes)


def get_base_domain(domain: str) -> str:
    """Get the base domain name for the given domain

    note:
        Results are based on a list of public domain suffixes at
        https://publicsuffix.org/list/public_suffix_list.dat.

    Args:
        domain: A domain or subdomain

    Returns:
        The base domain of the given domain

    """
    psl = publicsuffixlist.PublicSuffixList()
    return psl.privatesuffix(domain)


def query_dns(
    domain: str,
    record_type: str,
    cache: ExpiringDict | None = None,
    nameservers: list[str] | None = None,
    timeout: float = 2.0,
) -> list[str]:
    """Make a DNS query

    Args:
        domain: The domain or subdomain to query about
        record_type: The record type to query for
        cache: Cache storage
        nameservers: A list of one or more nameservers to use
            (Cloudflare's public DNS resolvers by default)
        timeout: Sets the DNS timeout in seconds

    Returns:
        A list of answers
    """
    domain = str(domain).lower()
    record_type = record_type.upper()
    cache_key = f"{domain}_{record_type}"
    if cache is not None:
        records = cache.get(cache_key, None)
        if records:
            return records

    resolver = dns.resolver.Resolver()
    timeout = float(timeout)
    if nameservers is None:
        nameservers = [
            "1.1.1.1",
            "1.0.0.1",
            "2606:4700:4700::1111",
            "2606:4700:4700::1001",
        ]
    resolver.nameservers = nameservers
    resolver.timeout = timeout
    resolver.lifetime = timeout
    if record_type == "TXT":
        resource_records = list(
            map(
                lambda r: r.strings,  # type: ignore[attr-defined]
                resolver.resolve(domain, record_type, lifetime=timeout),
            )
        )
        _resource_record = [
            resource_record[0][:0].join(resource_record)
            for resource_record in resource_records
            if resource_record
        ]
        records = [r.decode() for r in _resource_record]
    else:
        records = list(
            map(
                lambda r: r.to_text().replace('"', "").rstrip("."),
                resolver.resolve(domain, record_type, lifetime=timeout),
            )
        )
    if cache is not None:
        cache[cache_key] = records

    return records


def get_reverse_dns(
    ip_address: str,
    cache: ExpiringDict | None = None,
    nameservers: list[str] | None = None,
    timeout: float = 2.0,
) -> str | None:
    """Resolve an IP address to a hostname using a reverse DNS query

    Args:
        ip_address: The IP address to resolve
        cache: Cache storage
        nameservers: A list of one or more nameservers to use (Cloudflare's public DNS resolvers by default)
        timeout: Sets the DNS query timeout in seconds

    Returns:
        The reverse DNS hostname (if any)
    """
    hostname: str | None = None
    try:
        address = str(dns.reversename.from_address(ip_address))
        hostname = query_dns(address, "PTR", cache=cache, nameservers=nameservers, timeout=timeout)[
            0
        ]

    except dns.exception.DNSException:
        pass

    return hostname


def timestamp_to_datetime(timestamp: int) -> datetime:
    """Converts a UNIX/DMARC timestamp to a Python `datetime` object

    Args:
        timestamp: The timestamp

    Returns:
        The converted timestamp as a Python `datetime` object
    """
    return datetime.fromtimestamp(int(timestamp))


def timestamp_to_human(timestamp: int) -> str:
    """Converts a UNIX/DMARC timestamp to a human-readable string

    Args:
        timestamp: The timestamp

    Returns:
        The converted timestamp in `YYYY-MM-DD HH:MM:SS` format
    """
    return timestamp_to_datetime(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def human_timestamp_to_datetime(human_timestamp: str, to_utc: bool = False) -> datetime:
    """Converts a human-readable timestamp into a Python `datetime` object

    Args:
        human_timestamp: A timestamp string
        to_utc: Convert the timestamp to UTC

    Returns:
        The converted timestamp
    """

    human_timestamp = human_timestamp.replace("-0000", "")
    human_timestamp = parenthesis_regex.sub("", human_timestamp)

    dt = parse_date(human_timestamp)
    return dt.astimezone(timezone.utc) if to_utc else dt


def human_timestamp_to_timestamp(human_timestamp: str) -> float:
    """Converts a human-readable timestamp into a UNIX timestamp

    Args:
        human_timestamp: A timestamp in `YYYY-MM-DD HH:MM:SS` format

    Returns:
        The converted timestamp
    """
    human_timestamp = human_timestamp.replace("T", " ")
    return human_timestamp_to_datetime(human_timestamp).timestamp()


def get_ip_address_country(ip_address: str, db_path: str | None = None) -> str | None:
    """Get the ISO code for the country associated with the given IPv4 or IPv6 address

    Args:
        ip_address: The IP address to query for
        db_path: Path to a MMDB file from MaxMind or DBIP

    Returns:
        And ISO country code associated with the given IP address
    """
    db_paths = [
        "GeoLite2-Country.mmdb",
        "/usr/local/share/GeoIP/GeoLite2-Country.mmdb",
        "/usr/share/GeoIP/GeoLite2-Country.mmdb",
        "/var/lib/GeoIP/GeoLite2-Country.mmdb",
        "/var/local/lib/GeoIP/GeoLite2-Country.mmdb",
        "/usr/local/var/GeoIP/GeoLite2-Country.mmdb",
        "%SystemDrive%\\ProgramData\\MaxMind\\GeoIPUpdate\\GeoIP\\GeoLite2-Country.mmdb",
        "C:\\GeoIP\\GeoLite2-Country.mmdb",
        "dbip-country-lite.mmdb",
        "dbip-country.mmdb",
    ]

    if db_path is not None:
        if os.path.isfile(db_path) is False:
            db_path = None
            logger.warning(
                f"No file exists at {db_path}. "
                "Falling back to an included copy of the IPDB IP to Country Lite database."
            )

    if db_path is None:
        for system_path in db_paths:
            if os.path.exists(system_path):
                db_path = system_path
                break

    if db_path is None:
        # pylint: disable=deprecated-method
        # path is deprecated in 3.11, it's replacement, as_file only available in 3.9+
        with importlib.resources.path(parsedmarc.resources.dbip, "dbip-country-lite.mmdb") as path:
            db_path = str(path)

        db_age = datetime.now() - datetime.fromtimestamp(os.stat(db_path).st_mtime)
        if db_age > timedelta(days=30):
            logger.warning("IP database is more than a month old")

    db_reader = geoip2.database.Reader(db_path)

    country = None

    try:
        country = db_reader.country(ip_address).country.iso_code
    except geoip2.errors.AddressNotFoundError:
        pass

    return country


def get_ip_address_info(
    ip_address: str,
    ip_db_path: str | None = None,
    cache: ExpiringDict | None = None,
    offline: bool = False,
    nameservers: list[str] | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Get reverse DNS and country information for the given IP address

    Args:
        ip_address: The IP address to check
        ip_db_path: path to a MMDB file from MaxMind or DBIP
        cache: Cache storage
        offline: Do not make online queries for geolocation or DNS
        nameservers: A list of one or more nameservers to use (Cloudflare's public DNS resolvers by default)
        timeout: Sets the DNS timeout in seconds

    Returns:
        Dictionary of (`ip_address`, `country`, `reverse_dns`, `base_domain`)

    """
    ip_address = ip_address.lower()
    if cache is not None:
        info = cache.get(ip_address, None)
        if info:
            return info
    info = {}
    info["ip_address"] = ip_address
    if offline:
        reverse_dns = None
    else:
        reverse_dns = get_reverse_dns(
            ip_address, cache=cache, nameservers=nameservers, timeout=timeout
        )
    country = get_ip_address_country(ip_address, db_path=ip_db_path)
    info["country"] = country
    info["reverse_dns"] = reverse_dns
    info["base_domain"] = None
    if reverse_dns is not None:
        base_domain = get_base_domain(reverse_dns)
        info["base_domain"] = base_domain

    return info


def parse_email_address(original_address: str) -> dict[str, Any]:
    """Parse an email into parts"""
    if original_address[0] == "":
        display_name = None
    else:
        display_name = original_address[0]
    address = original_address[1]
    address_parts = address.split("@")
    local = None
    domain = None
    if len(address_parts) > 1:
        local = address_parts[0].lower()
        domain = address_parts[-1].lower()

    return {
        "display_name": display_name,
        "address": address,
        "local": local,
        "domain": domain,
    }


def get_filename_safe_string(string: str) -> str:
    """Convert a string to a string that is safe for a filename

    Args:
        string: A string to make safe for a filename

    Returns:
        A string safe for a filename
    """
    invalid_filename_chars = ["\\", "/", ":", '"', "*", "?", "|", "\n", "\r"]
    if string is None:
        string = "None"
    for char in invalid_filename_chars:
        string = string.replace(char, "")
    string = string.rstrip(".")

    string = (string[:100]) if len(string) > 100 else string

    return string


def is_mbox(path: str) -> bool:
    """Checks if the given content is an MBOX mailbox file

    Args:
        Content to check

    Returns:
        If the file is an MBOX mailbox file
    """
    _is_mbox = False
    try:
        mbox = mailbox.mbox(path)
        if len(mbox.keys()) > 0:
            _is_mbox = True
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.debug(f"Error checking for MBOX file: {e!r}")

    return _is_mbox


def is_outlook_msg(content: Any) -> bool:
    """Checks if the given content is an Outlook msg OLE/MSG file

    Args:
        content: Content to check

    Returns:
        If the file is an Outlook MSG file
    """
    return isinstance(content, bytes) and content.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1")


def convert_outlook_msg(msg_bytes: bytes) -> bytes:
    """Convert an Outlook MS file to standard RFC 822 format

    Requires the `msgconvert` Perl utility to be installed.

    Args:
        msg_bytes: the content of the .msg file

    Returns:
        A RFC 822 string
    """
    if not is_outlook_msg(msg_bytes):
        raise ValueError("The supplied bytes are not an Outlook MSG file")
    orig_dir = os.getcwd()
    tmp_dir = tempfile.mkdtemp()
    os.chdir(tmp_dir)
    with open("sample.msg", "wb") as msg_file:
        msg_file.write(msg_bytes)
    try:
        subprocess.check_call(
            ["msgconvert", "sample.msg"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        with open("sample.eml", "rb") as eml_file:
            rfc822 = eml_file.read()
    except FileNotFoundError:
        # pylint: disable=raise-missing-from
        raise EmailParserError("Failed to convert Outlook MSG: msgconvert utility not found")
    finally:
        os.chdir(orig_dir)
        shutil.rmtree(tmp_dir)

    return rfc822


def parse_email(data: bytes | str, strip_attachment_payloads: bool = False) -> dict[str, Any]:
    """A simplified email parser

    Args:
        data: The RFC 822 message string, or MSG binary
        strip_attachment_payloads: Remove attachment payloads

    Returns:
        Parsed email data
    """

    # pylint: disable=too-many-nested-blocks

    if isinstance(data, bytes):
        if is_outlook_msg(data):
            data = convert_outlook_msg(data)
        data = data.decode("utf-8", errors="replace")
    parsed_email = mailparser.parse_from_string(data)
    headers = json.loads(parsed_email.headers_json).copy()
    parsed_email = json.loads(parsed_email.mail_json).copy()
    parsed_email["headers"] = headers

    if "received" in parsed_email:
        for received in parsed_email["received"]:
            if "date_utc" in received:
                if received["date_utc"] is None:
                    del received["date_utc"]
                else:
                    received["date_utc"] = received["date_utc"].replace("T", " ")

    if "from" not in parsed_email:
        if "From" in parsed_email["headers"]:
            parsed_email["from"] = parsed_email["Headers"]["From"]
        else:
            parsed_email["from"] = None

    if parsed_email["from"] is not None:
        parsed_email["from"] = parse_email_address(parsed_email["from"][0])

    if "date" in parsed_email:
        parsed_email["date"] = parsed_email["date"].replace("T", " ")
    else:
        parsed_email["date"] = None

    for email_field in ["reply_to", "to", "cc", "bcc", "delivered_to"]:
        parsed_email[email_field] = [
            parse_email_address(email) for email in parsed_email.get(email_field, [])
        ]

    if "attachments" not in parsed_email:
        parsed_email["attachments"] = []
    else:
        for attachment in parsed_email["attachments"]:
            if "payload" in attachment:
                payload = attachment["payload"]
                try:
                    if "content_transfer_encoding" in attachment:
                        if attachment["content_transfer_encoding"] == "base64":
                            payload = decode_base64(payload)
                        else:
                            payload = str.encode(payload)
                    attachment["sha256"] = hashlib.sha256(payload).hexdigest()
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.debug(f"Unable to decode attachment: {e!r}")
        if strip_attachment_payloads:
            for attachment in parsed_email["attachments"]:
                if "payload" in attachment:
                    del attachment["payload"]

    if "subject" not in parsed_email:
        parsed_email["subject"] = None

    parsed_email["filename_safe_subject"] = get_filename_safe_string(parsed_email["subject"])

    if "body" not in parsed_email:
        parsed_email["body"] = None

    return parsed_email


def extract_xml(source: str | bytes | BinaryIO) -> str:
    """Extracts xml from a zip or gzip file at the given path, file-like object, or bytes.

    Args:
        source: A path to a file, a file like object, or bytes

    Returns:
        The extracted XML
    """
    file_object: BinaryIO
    try:
        if isinstance(source, str):
            file_object = open(source, "rb")  # pylint: disable=consider-using-with
        elif isinstance(source, bytes):
            file_object = BytesIO(source)
        else:
            file_object = source

        header = file_object.read(6)
        file_object.seek(0)

        if header.startswith(const.MAGIC_ZIP):
            with zipfile.ZipFile(file_object) as _zip:
                with _zip.open(_zip.namelist()[0]) as f:
                    xml = f.read().decode(errors="ignore")

        elif header.startswith(const.MAGIC_GZIP):
            xml = zlib.decompress(file_object.read(), zlib.MAX_WBITS | 16).decode(errors="ignore")

        elif header.startswith(const.MAGIC_XML):
            xml = file_object.read().decode(errors="ignore")

        else:
            # raise InvalidAggregateReport("Not a valid zip, gzip, or xml file")
            raise ValueError("Not a valid zip, gzip, or xml file")

    except UnicodeDecodeError:
        # pylint: disable=raise-missing-from
        raise ValueError("File objects must be opened in binary (rb) mode")

    except Exception as error:
        raise ValueError(f"Invalid archive file: {error!r}") from error

    finally:
        file_object.close()

    return xml


def load_bytes_from_source(source: str | bytes | BinaryIO):
    """Load bytes from source.

    Args:
        source: A path to a file, a file like object, or bytes.
    """
    if isinstance(source, bytes):
        return source
    if isinstance(source, str):
        with open(source, "rb") as f:
            return f.read()
    if isinstance(source, BinaryIO):
        source.seek(0)
        return source.read()
    raise ValueError(f"Unsupported source: {type(source)}")


class MboxIterator:
    """Class that allows iterating through all messages in an mbox file

    Returns tuples of `(message_key, message)`.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.mbox = mailbox.mbox(path, create=False)
        self._message_keys: deque[str] = deque(self.mbox.keys())
        return

    def __next__(self) -> tuple[str, str]:
        if not self._message_keys:
            raise StopIteration()

        message_key = self._message_keys.popleft()
        return (message_key, self.mbox.get_string(message_key))

    def __iter__(self) -> MboxIterator:
        return self

    def __bool__(self) -> bool:
        return bool(self._message_keys)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.path!r})"

    def __str__(self) -> str:
        return repr(self)
