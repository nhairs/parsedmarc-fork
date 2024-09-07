### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
from typing import Any, Dict, Type

# Installed
import pytest

# Package
from parsedmarc.parser import ReportParser
from parsedmarc.sink.base import Sink
import parsedmarc.sink.elasticsearch
import parsedmarc.sink.util
import parsedmarc.source.aws
from parsedmarc.source.base import Source
import parsedmarc.source.email
import parsedmarc.source.file
import parsedmarc.source.util

### SETUP
### ============================================================================
PARSER = ReportParser()


### TESTS
### ============================================================================
@pytest.mark.parametrize(
    "class_, config",
    [
        # AWS
        (parsedmarc.source.aws.SimpleEmailService, {"queue_name": "foo"}),
        (
            parsedmarc.source.aws.SimpleEmailService,
            {
                "queue_name": "foo",
                "session": {"region_name": "ap-southeast-2"},
            },
        ),
        # Email
        (
            parsedmarc.source.email.Imap,
            {"host": "example.org", "username": "nicholas", "password": "secret"},
        ),
        (parsedmarc.source.email.Google, {"credentials_file": "/home/user/.parsedmarc"}),
        (
            parsedmarc.source.email.MicrosoftGraph,
            {
                "auth_method": "UsernamePassword",
                "client_id": "1234asdf",
                "client_secret": "secret",
                "username": "nicholas",
                "password": "secret",
            },
        ),
        (
            parsedmarc.source.email.MicrosoftGraph,
            {
                "auth_method": "DeviceCode",
                "client_id": "1234asdf",
                "client_secret": "secret",
                "tenant_id": "1234asdf",
            },
        ),
        (
            parsedmarc.source.email.MicrosoftGraph,
            {
                "auth_method": "ClientSecret",
                "client_id": "1234asdf",
                "client_secret": "secret",
                "tenant_id": "1234asdf",
            },
        ),
        # File
        (
            parsedmarc.source.file.DirectoriesAndFiles,
            {"paths": ["/tmp/parsedmarc.d", "/tmp/parsedmarc_reports/report.eml", "./"]},
        ),
        # Util
        (parsedmarc.source.util.StaticAggregateReportGenerator, {"report": {"foo": "bar"}}),
        (parsedmarc.source.util.RandomAggregateReportGenerator, {}),
        (parsedmarc.source.util.MalformedAggregateReportGenerator, {}),
        (parsedmarc.source.util.StaticForensicReportGenerator, {"report": {"foo": "bar"}}),
        (parsedmarc.source.util.RandomForensicReportGenerator, {}),
        (parsedmarc.source.util.MalformedForensicReportGenerator, {}),
    ],
)
def test_source_init(class_: Type[Source], config: Dict[str, Any]):
    source = class_("test", PARSER, config)
    return


@pytest.mark.parametrize(
    "class_, config",
    [
        # ElasticSearch
        (parsedmarc.sink.elasticsearch.Elasticsearch, {"client": {"foo": "bar"}}),
        # Util
        (parsedmarc.sink.util.Noop, {}),
        (parsedmarc.sink.util.Console, {}),
    ],
)
def test_sink_init(class_: Type[Sink], config: Dict[str, Any]):
    sink = class_("test", config)
    return
