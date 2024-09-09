"""Utitily Sources

These Sources are not intended to be used in production.
"""

### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
from copy import deepcopy
import random
import time
from typing import Any, Dict, Union
import uuid

# Local
from ..const import AppState
from ..report import AggregateReport, ForensicReport, Report
from .base import BaseConfig, Job, Source


### CLASSES
### ============================================================================
class UtilitySource(Source):
    """Base class for utility sources.

    This class should not be used directly.

    Child classes MUST implement `self.make_report`.

    *New in 9.0*.
    """

    config: UtilityConfig

    def get_job(self) -> Job:
        if self._state != AppState.RUNNING:
            raise RuntimeError("Source is not running")

        self.sleep()
        job = Job(source=self, report=self.make_report(), identifier=str(uuid.uuid4()))
        self.register_job(job)
        return job

    def make_report(self) -> Report:
        raise NotImplementedError("Child classes must implement make_report")

    def sleep(self) -> None:
        """Sleep for the configured time"""
        sleep_time: int | float | None
        if self.config.sleep_enabled:
            if (sleep_time := self.config.sleep_time) is None:
                sleep_time = random.uniform(self.config.sleep_min, self.config.sleep_max)
            time.sleep(sleep_time)
        return


class UtilityConfig(BaseConfig):
    """Utility Config

    *New in 9.0*.
    """

    sleep_enabled: bool = True
    sleep_time: Union[int, None] = None
    sleep_min: Union[int, float] = 0.2
    sleep_max: Union[int, float] = 1.5


class ReportConfig(UtilityConfig):
    """Report Config.

    *New in 9.0*.
    """

    report: Union[Dict[str, Any], None] = None


## DMARC Reports
## -----------------------------------------------------------------------------
# Aggregate Reports
# ..............................................................................
class StaticAggregateReportGenerator(UtilitySource):
    """Source that produces the same `AggregateReport` every time

    Useful for duplicate report testing

    Config:
        `report: dict[str, Any]`: static report to use instead of the default one.

    *New in 9.0*.
    """

    config: ReportConfig

    _report = {
        "xml_schema": "1.0",
        "report_metadata": {
            "org_name": "usssa.com",
            "org_email": "postmaster@usssa.com",
            "org_extra_contact_info": None,
            "report_id": "8953b4d4a4ee4218b6ac0e2cb2667ee1",
            "begin_date": "2018-10-06 10:00:00",
            "end_date": "2018-10-07 10:59:59",
            "errors": [],
        },
        "policy_published": {
            "domain": "example.com",
            "adkim": "r",
            "aspf": "r",
            "p": "none",
            "sp": "none",
            "pct": "100",
            "fo": "0",
        },
        "records": [
            {
                "source": {
                    "ip_address": "12.20.127.40",
                    "country": "US",
                    "reverse_dns": "smtp3.cardinal.com",
                    "base_domain": "cardinal.com",
                },
                "count": 1,
                "alignment": {"spf": False, "dkim": False, "dmarc": False},
                "policy_evaluated": {
                    "disposition": "none",
                    "dkim": "fail",
                    "spf": "fail",
                    "policy_override_reasons": [],
                },
                "identifiers": {
                    "envelope_from": None,
                    "header_from": "example.com",
                    "envelope_to": None,
                },
                "auth_results": {"dkim": [], "spf": []},
            },
            {
                "source": {
                    "ip_address": "199.230.200.36",
                    "country": "US",
                    "reverse_dns": "smtp7.cardinal.com",
                    "base_domain": "cardinal.com",
                },
                "count": 1,
                "alignment": {"spf": False, "dkim": False, "dmarc": False},
                "policy_evaluated": {
                    "disposition": "none",
                    "dkim": "fail",
                    "spf": "fail",
                    "policy_override_reasons": [],
                },
                "identifiers": {
                    "envelope_from": None,
                    "header_from": "example.com",
                    "envelope_to": None,
                },
                "auth_results": {"dkim": [], "spf": []},
            },
        ],
    }

    def make_report(self) -> AggregateReport:
        if (report := self.config.report) is None:
            report = self._report
        return AggregateReport(deepcopy(report))


class RandomAggregateReportGenerator(UtilitySource):
    """Source that produces random `AggregateReport`s

    Useful for testing.

    Note: reports are randomly generates which means that although unlikely it is
    possible that duplicate reports will be generated.

    *New in 9.0*.
    """

    def make_report(self) -> AggregateReport:
        # data = {"a": 1}
        # return AggregateReport(data)
        raise NotImplementedError()


class MalformedAggregateReportGenerator(UtilitySource):
    """Source that produces malformed `AggregateReport`s

    Useful for testing.

    *New in 9.0*.
    """

    def make_report(self) -> AggregateReport:
        data = {"a": 1}
        return AggregateReport(data)


# Forensic Reports
# ..............................................................................
class StaticForensicReportGenerator(UtilitySource):
    """Source that produces the same `ForensicReport` every time

    Useful for duplicate report testing

    Config:
        `report: dict[str, Any]`: static report to use instead of the default one.

    *New in 9.0*.
    """

    config: ReportConfig

    _report = {
        "feedback_type": "auth-failure",
        "user_agent": "Lua/1.0",
        "version": "1.0",
        "original_rcpt_to": "recipient@linkedin.com",
        "arrival_date": "Tue, 30 Apr 2019 02:09:00 +0000",
        "message_id": "<01010101010101010101010101010101@ABAB01MS0016.someserver.loc>",
        "authentication_results": "dmarc=fail (p=none; dis=none) header.from=example.com",
        "delivery_result": "delivered",
        "auth_failure": ["dmarc"],
        "reported_domain": "example.com",
        "arrival_date_utc": "2019-04-30 02:09:00",
        "source": {
            "ip_address": "10.10.10.10",
            "country": None,
            "reverse_dns": None,
            "base_domain": None,
        },
        "authentication_mechanisms": [],
        "original_envelope_id": None,
        "dkim_domain": None,
        "original_mail_from": None,
        "sample_headers_only": False,
        "sample": 'Return-Path: <>\nAuthentication-Results: mail516.prod.linkedin.com; iprev=pass policy.iprev="10.10.10.10"; spf=neutral smtp.mailfrom="" smtp.helo="mail02.someserver.com"; dkim=none (message not signed) header.d=none; tls=pass (verified) key.ciphersuite="TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384" key.length="256" tls.v="tlsv1.2" cert.client="OU=Domain Control Validated,CN=*.someserver.com" cert.clientissuer="C=GB,ST=Greater Manchester,L=Salford,O=COMODO CA Limited,CN=COMODO RSA Domain Validation Secure Server CA"; dmarc=fail (p=none; dis=none) header.from=example.com\nX-OnPremExternalIP: 10.10.10.10\nReceived: from [10.10.10.10] ([10.10.10.10:4227] helo=mail02.someserver.com)\n\tby mail516.prod.linkedin.com (envelope-from <>)\n\t(ecelerity 3.6.21.53563 r(Core:3.6.21.0)) with ESMTPS (cipher=ECDHE-RSA-AES256-GCM-SHA384\n\tsubject="/OU=Domain Control Validated/CN=*.someserver.com")\n\tid CA/91-26019-ABCDECC5; Tue, 30 Apr 2019 02:09:00 +0000\nReceived: from DENU02MS0016.someserver.loc (10.156.68.14) by\n DENU02MS0017.someserver.loc (10.10.10.9) with Microsoft SMTP Server (TLS) id\n 15.0.1367.3; Tue, 30 Apr 2019 04:09:09 +0200\nReceived: from DENU02MS0016.someserver.loc ([127.0.0.1]) by\n DENU02MS0016.someserver.loc ([10.10.10.8]) with Microsoft SMTP Server id\n 15.00.1367.000; Tue, 30 Apr 2019 04:09:09 +0200\nFrom: Sender <sender@example.com>\nTo: LinkedIn <recipient@linkedin.com>\nSubject: Subject line, could be UTF8 encoded\nThread-Topic: Thread Topic line, could be UTF8 encoded\nThread-Index: AQHU/abcdW8+abcdLkClF52hP4alIaZT9XGh\nDate: Tue, 30 Apr 2019 02:09:09 +0000\nMessage-ID: <01010101010101010101010101010101@ABAB01MS0016.someserver.loc>\nReferences: <1111111111.1111111.1111111111111.JavaMail.app@lor1-app3586.prod.linkedin.com>\nIn-Reply-To: <1111111111.1111111.1111111111111.JavaMail.app@lor1-app3586.prod.linkedin.com>\nX-MS-Has-Attach: \nX-Auto-Response-Suppress: All\nX-MS-Exchange-Inbox-Rules-Loop: sender@example.com\nX-MS-TNEF-Correlator: \nx-ms-exchange-transport-fromentityheader: Hosted\nx-ms-exchange-parent-message-id: <1111111111.1111111.1111111111111.JavaMail.app@lor1-app3586.prod.linkedin.com>\nauto-submitted: auto-generated\nx-ms-exchange-generated-message-source: Mailbox Rules Agent\nx-exclaimer-md-config: 11111111-1111-1111-1111-111111111111\nContent-Type: multipart/alternative;\n\tboundary="_000_0d00000000000000000d000000000000f00000s00000someserverloc_"\nMIME-Version: 1.0\nX-Linkedin-fe: false\n\n--_000_0d00000000000000000d000000000000f00000s00000someserverloc_\nContent-Type: text/plain; charset="iso-8859-1"\nContent-Transfer-Encoding: quoted-printable\n\nAlternative\nText\n\n--_000_0d00000000000000000d000000000000f00000s00000someserverloc_\nContent-Type: text/html; charset="iso-8859-1"\nContent-Transfer-Encoding: quoted-printable\n\n<html>\n<head>\n</head>\n<body>\nHTML Text\n</body>\n</html>\n\n--_000_0d00000000000000000d000000000000f00000s00000someserverloc_--\n',
        "parsed_sample": {
            "references": "<1111111111.1111111.1111111111111.JavaMail.app@lor1-app3586.prod.linkedin.com>",
            "subject": "Subject line, could be UTF8 encoded",
            "x-linkedin-fe": "false",
            "x-ms-exchange-transport-fromentityheader": "Hosted",
            "x-auto-response-suppress": "All",
            "thread-index": "AQHU/abcdW8+abcdLkClF52hP4alIaZT9XGh",
            "x-ms-exchange-inbox-rules-loop": "sender@example.com",
            "auto-submitted": "auto-generated",
            "thread-topic": "Thread Topic line, could be UTF8 encoded",
            "x-ms-exchange-parent-message-id": "<1111111111.1111111.1111111111111.JavaMail.app@lor1-app3586.prod.linkedin.com>",
            "return-path": "<>",
            "content-type": 'multipart/alternative;\n\tboundary="_000_0d00000000000000000d000000000000f00000s00000someserverloc_"',
            "to_domains": ["linkedin.com"],
            "message-id": "<01010101010101010101010101010101@ABAB01MS0016.someserver.loc>",
            "x-onpremexternalip": "10.10.10.10",
            "authentication-results": 'mail516.prod.linkedin.com; iprev=pass policy.iprev="10.10.10.10"; spf=neutral smtp.mailfrom="" smtp.helo="mail02.someserver.com"; dkim=none (message not signed) header.d=none; tls=pass (verified) key.ciphersuite="TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384" key.length="256" tls.v="tlsv1.2" cert.client="OU=Domain Control Validated,CN=*.someserver.com" cert.clientissuer="C=GB,ST=Greater Manchester,L=Salford,O=COMODO CA Limited,CN=COMODO RSA Domain Validation Secure Server CA"; dmarc=fail (p=none; dis=none) header.from=example.com',
            "received": [
                {
                    "from": "DENU02MS0016.someserver.loc 127.0.0.1",
                    "by": "DENU02MS0016.someserver.loc 10.10.10.8",
                    "with": "Microsoft SMTP Server",
                    "id": "15.00.1367.000",
                    "date": "Tue, 30 Apr 2019 04:09:09 +0200",
                    "hop": 1,
                    "date_utc": "2019-04-30 02:09:09",
                    "delay": 0,
                },
                {
                    "from": "DENU02MS0016.someserver.loc 10.156.68.14",
                    "by": "DENU02MS0017.someserver.loc 10.10.10.9",
                    "with": "Microsoft SMTP Server TLS",
                    "id": "15.0.1367.3",
                    "date": "Tue, 30 Apr 2019 04:09:09 +0200",
                    "hop": 2,
                    "date_utc": "2019-04-30 02:09:09",
                    "delay": 0.0,
                },
                {
                    "from": "10.10.10.10 10.10.10.10:4227 helo=mail02.someserver.com",
                    "by": "mail516.prod.linkedin.com",
                    "with": 'ESMTPS cipher=ECDHE-RSA-AES256-GCM-SHA384 subject="/OU=Domain Control Validated/CN=*.someserver.com"',
                    "id": "CA/91-26019-ABCDECC5",
                    "date": "Tue, 30 Apr 2019 02:09:00 +0000",
                    "hop": 3,
                    "date_utc": "2019-04-30 02:09:00",
                    "delay": -9.0,
                },
            ],
            "x-exclaimer-md-config": "11111111-1111-1111-1111-111111111111",
            "x-ms-exchange-generated-message-source": "Mailbox Rules Agent",
            "from": {
                "display_name": "Sender",
                "address": "sender@example.com",
                "local": "sender",
                "domain": "example.com",
            },
            "body": "Alternative\nText\n\n--- mail_boundary ---\n<html>\n<head>\n</head>\n<body>\nHTML Text\n</body>\n</html>\n",
            "to": [
                {
                    "display_name": "LinkedIn",
                    "address": "recipient@linkedin.com",
                    "local": "recipient",
                    "domain": "linkedin.com",
                }
            ],
            "timezone": "+0.0",
            "mime-version": "1.0",
            "in-reply-to": "<1111111111.1111111.1111111111111.JavaMail.app@lor1-app3586.prod.linkedin.com>",
            "date": "2019-04-30 02:09:09",
            "has_defects": False,
            "headers": {
                "Return-Path": "<>",
                "Authentication-Results": 'mail516.prod.linkedin.com; iprev=pass policy.iprev="10.10.10.10"; spf=neutral smtp.mailfrom="" smtp.helo="mail02.someserver.com"; dkim=none (message not signed) header.d=none; tls=pass (verified) key.ciphersuite="TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384" key.length="256" tls.v="tlsv1.2" cert.client="OU=Domain Control Validated,CN=*.someserver.com" cert.clientissuer="C=GB,ST=Greater Manchester,L=Salford,O=COMODO CA Limited,CN=COMODO RSA Domain Validation Secure Server CA"; dmarc=fail (p=none; dis=none) header.from=example.com',
                "X-OnPremExternalIP": "10.10.10.10",
                "Received": "from DENU02MS0016.someserver.loc ([127.0.0.1]) by\n DENU02MS0016.someserver.loc ([10.10.10.8]) with Microsoft SMTP Server id\n 15.00.1367.000; Tue, 30 Apr 2019 04:09:09 +0200",
                "From": "Sender <sender@example.com>",
                "To": "LinkedIn <recipient@linkedin.com>",
                "Subject": "Subject line, could be UTF8 encoded",
                "Thread-Topic": "Thread Topic line, could be UTF8 encoded",
                "Thread-Index": "AQHU/abcdW8+abcdLkClF52hP4alIaZT9XGh",
                "Date": "Tue, 30 Apr 2019 02:09:09 +0000",
                "Message-ID": "<01010101010101010101010101010101@ABAB01MS0016.someserver.loc>",
                "References": "<1111111111.1111111.1111111111111.JavaMail.app@lor1-app3586.prod.linkedin.com>",
                "In-Reply-To": "<1111111111.1111111.1111111111111.JavaMail.app@lor1-app3586.prod.linkedin.com>",
                "X-MS-Has-Attach": "",
                "X-Auto-Response-Suppress": "All",
                "X-MS-Exchange-Inbox-Rules-Loop": "sender@example.com",
                "X-MS-TNEF-Correlator": "",
                "x-ms-exchange-transport-fromentityheader": "Hosted",
                "x-ms-exchange-parent-message-id": "<1111111111.1111111.1111111111111.JavaMail.app@lor1-app3586.prod.linkedin.com>",
                "auto-submitted": "auto-generated",
                "x-ms-exchange-generated-message-source": "Mailbox Rules Agent",
                "x-exclaimer-md-config": "11111111-1111-1111-1111-111111111111",
                "Content-Type": 'multipart/alternative;\n\tboundary="_000_0d00000000000000000d000000000000f00000s00000someserverloc_"',
                "MIME-Version": "1.0",
                "X-Linkedin-fe": "false",
            },
            "reply_to": [],
            "cc": [],
            "bcc": [],
            "attachments": [],
            "filename_safe_subject": "Subject line, could be UTF8 encoded",
        },
    }

    def make_report(self) -> ForensicReport:
        if (report := self.config.report) is None:
            report = self._report
        return ForensicReport(deepcopy(report))


class RandomForensicReportGenerator(UtilitySource):
    """Source that produces random `ForensicReport`s

    Useful for testing.

    Note: reports are randomly generates which means that although unlikely it is
    possible that duplicate reports will be generated.

    *New in 9.0*.
    """

    def make_report(self) -> ForensicReport:
        # data = {"a": 1}
        # return ForensicReport(data)
        raise NotImplementedError()


class MalformedForensicReportGenerator(UtilitySource):
    """Source that produces malformed `ForensicReport`s

    Useful for testing.

    *New in 9.0*.
    """

    def make_report(self) -> ForensicReport:
        data = {"a": 1}
        return ForensicReport(data)
