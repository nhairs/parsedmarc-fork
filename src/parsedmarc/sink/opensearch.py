### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
import datetime
from typing import Any, List, Literal, Union

# Installed
import opensearchpy
from opensearchpy import (
    Boolean,
    Date,
    Document,
    Index,
    InnerDoc,
    Integer,
    Ip,
    Nested,
    Object,
    Q,
    Search,
    Text,
)
from pydantic import BaseModel

# Local
from ..const import AppState
from ..report import AggregateReport, ForensicReport
from ..utils import human_timestamp_to_datetime
from .base import BaseConfig, Sink


### CLASSES
### ============================================================================
class OpenSearch(Sink):
    """Stores reports in OpenSearch.

    *New in 9.0*.
    """

    config: OpenSearchConfig

    INDEX_VERSION: int = 2

    def setup(self) -> None:
        if self._state != AppState.SHUTDOWN:
            raise RuntimeError("Sink is already running")
        self._state = AppState.SETTING_UP

        try:
            ## Prepare index names
            self.aggregate_index_base = f"{self.config.index_prefix}dmarc_aggregate"
            self.forensic_index_base = f"{self.config.index_prefix}dmarc_forensic"

            if self.config.index_suffix:
                self.aggregate_index_base += f"_{self.config.index_suffix}"
                self.forensic_index_base += f"_{self.config.index_suffix}"

            ## Create client
            kwargs: dict[str, Any] = {"timeout": self.config.client.timeout}

            if isinstance(self.config.client.hosts, str):
                kwargs["hosts"] = [self.config.client.hosts]
            else:
                kwargs["hosts"] = self.config.client.hosts

            if self.config.client.username:
                kwargs["http_auth"] = f"{self.config.client.username}:{self.config.client.password}"

            if self.config.client.api_key:
                kwargs["api_key"] = self.config.client.api_key

            if self.config.client.ssl:
                kwargs["use_ssl"] = True
                if self.config.client.cert_path:
                    kwargs["verify_certs"] = True
                    kwargs["ca_certs"] = self.config.client.cert_path
                else:
                    kwargs["verify_certs"] = False
            else:
                kwargs["use_ssl"] = False

            self.client = opensearchpy.OpenSearch(**kwargs)

            ## Migrate old indexes
            self._migrate_indexes()

        except:
            self._state = AppState.SETUP_ERROR
            raise

        self._state = AppState.RUNNING
        return

    def cleanup(self) -> None:
        super().cleanup()
        self.client.close()
        return

    def process_aggregate_report(self, report: AggregateReport) -> None:
        data = report.data.copy()

        metadata = data["report_metadata"]
        org_name = metadata["org_name"]
        report_id = metadata["report_id"]
        domain = data["policy_published"]["domain"]
        begin_date = human_timestamp_to_datetime(metadata["begin_date"], to_utc=True)
        end_date = human_timestamp_to_datetime(metadata["end_date"], to_utc=True)
        # begin_date_human = begin_date.strftime("%Y-%m-%d %H:%M:%SZ")
        # end_date_human = end_date.strftime("%Y-%m-%d %H:%M:%SZ")

        data["begin_date"] = begin_date
        data["end_date"] = end_date
        date_range = [data["begin_date"], data["end_date"]]

        # pylint: disable=use-dict-literal
        org_name_query = Q(dict(match_phrase=dict(org_name=org_name)))
        report_id_query = Q(dict(match_phrase=dict(report_id=report_id)))
        domain_query = Q(dict(match_phrase={"published_policy.domain": domain}))
        begin_date_query = Q(dict(match=dict(date_begin=begin_date)))
        end_date_query = Q(dict(match=dict(date_end=end_date)))
        # pylint: enable=use-dict-literal

        search = Search(index=f"{self.aggregate_index_base}*", using=self.client)
        search.query = (
            org_name_query & report_id_query & domain_query & begin_date_query & end_date_query
        )

        existing = search.execute()

        if len(existing) > 0:
            if self.config.on_duplicate == "discard":
                self.info(
                    f"Discarding duplicate report: ID {report_id} from {org_name} about {domain} with a date range of {begin_date} to {end_date}"
                )
                return
            # We should not get to here, but just in case
            raise RuntimeError("Duplicate report without way to handle")

        ## Create Index
        index = self._get_index_name(self.aggregate_index_base, begin_date)
        self._create_indexes(index)

        ## Save Agrgegate Report Records
        published_policy = _PublishedPolicy(
            domain=data["policy_published"]["domain"],
            adkim=data["policy_published"]["adkim"],
            aspf=data["policy_published"]["aspf"],
            p=data["policy_published"]["p"],
            sp=data["policy_published"]["sp"],
            pct=data["policy_published"]["pct"],
            fo=data["policy_published"]["fo"],
        )

        for record in data["records"]:
            agg_doc = _AggregateReportDoc(
                xml_schema=data["xml_schema"],
                org_name=metadata["org_name"],
                org_email=metadata["org_email"],
                org_extra_contact_info=metadata["org_extra_contact_info"],
                report_id=metadata["report_id"],
                date_range=date_range,
                date_begin=data["begin_date"],
                date_end=data["end_date"],
                errors=metadata["errors"],
                published_policy=published_policy,
                source_ip_address=record["source"]["ip_address"],
                source_country=record["source"]["country"],
                source_reverse_dns=record["source"]["reverse_dns"],
                source_base_domain=record["source"]["base_domain"],
                source_type=record["source"]["type"],
                source_name=record["source"]["name"],
                message_count=record["count"],
                disposition=record["policy_evaluated"]["disposition"],
                dkim_aligned=record["policy_evaluated"]["dkim"] is not None
                and record["policy_evaluated"]["dkim"].lower() == "pass",
                spf_aligned=record["policy_evaluated"]["spf"] is not None
                and record["policy_evaluated"]["spf"].lower() == "pass",
                header_from=record["identifiers"]["header_from"],
                envelope_from=record["identifiers"]["envelope_from"],
                envelope_to=record["identifiers"]["envelope_to"],
                using=self.client,
            )

            for override in record["policy_evaluated"]["policy_override_reasons"]:
                agg_doc.add_policy_override(type_=override["type"], comment=override["comment"])

            for dkim_result in record["auth_results"]["dkim"]:
                agg_doc.add_dkim_result(
                    domain=dkim_result["domain"],
                    selector=dkim_result["selector"],
                    result=dkim_result["result"],
                )

            for spf_result in record["auth_results"]["spf"]:
                agg_doc.add_spf_result(
                    domain=spf_result["domain"],
                    scope=spf_result["scope"],
                    result=spf_result["result"],
                )

            ## Save document
            agg_doc.meta.index = index
            agg_doc.save()
        return

    def process_forensic_report(self, report: ForensicReport) -> None:
        data = report.data.copy()

        sample_date = None
        if data["parsed_sample"]["date"] is not None:
            sample_date = data["parsed_sample"]["date"]
            sample_date = human_timestamp_to_datetime(sample_date)
        original_headers = data["parsed_sample"]["headers"]
        headers: dict[str, str] = {}
        for original_header in original_headers:
            headers[original_header.lower()] = original_headers[original_header]

        arrival_date = human_timestamp_to_datetime(data["arrival_date_utc"])

        search = Search(index=f"{self.forensic_index_base}*", using=self.client)
        arrival_query = {"match": {"arrival_date": arrival_date}}
        q = Q(arrival_query)

        from_ = None
        to_ = None
        subject = None
        if "from" in headers:
            from_ = headers["from"]
            from_query = {"match_phrase": {"sample.headers.from": from_}}
            q = q & Q(from_query)
        if "to" in headers:
            to_ = headers["to"]
            to_query = {"match_phrase": {"sample.headers.to": to_}}
            q = q & Q(to_query)
        if "subject" in headers:
            subject = headers["subject"]
            subject_query = {"match_phrase": {"sample.headers.subject": subject}}
            q = q & Q(subject_query)

        search.query = q
        existing = search.execute()

        if len(existing) > 0:
            if self.config.on_duplicate == "discard":
                self.info(
                    f"Discarding duplicate sample: to {to_} from {from_} with a subject of {subject} and arrival date of {arrival_date}"
                )
                return
            # We should not get to here, but just in case
            raise RuntimeError("Duplicate report without way to handle")

        ## Create Index
        index = self._get_index_name(self.forensic_index_base, arrival_date)
        self._create_indexes(index)

        ## Save Forensic Report
        parsed_sample = data["parsed_sample"]
        sample = _ForensicSampleDoc(
            raw=data["sample"],
            headers=headers,
            headers_only=data["sample_headers_only"],
            date=sample_date,
            subject=data["parsed_sample"]["subject"],
            filename_safe_subject=parsed_sample["filename_safe_subject"],
            body=data["parsed_sample"]["body"],
        )

        for address in data["parsed_sample"]["to"]:
            sample.add_to(display_name=address["display_name"], address=address["address"])
        for address in data["parsed_sample"]["reply_to"]:
            sample.add_reply_to(display_name=address["display_name"], address=address["address"])
        for address in data["parsed_sample"]["cc"]:
            sample.add_cc(display_name=address["display_name"], address=address["address"])
        for address in data["parsed_sample"]["bcc"]:
            sample.add_bcc(display_name=address["display_name"], address=address["address"])
        for attachment in data["parsed_sample"]["attachments"]:
            sample.add_attachment(
                filename=attachment["filename"],
                content_type=attachment["mail_content_type"],
                sha256=attachment["sha256"],
            )
        forensic_doc = _ForensicReportDoc(
            feedback_type=data["feedback_type"],
            user_agent=data["user_agent"],
            version=data["version"],
            original_mail_from=data["original_mail_from"],
            arrival_date=arrival_date,
            domain=data["reported_domain"],
            original_envelope_id=data["original_envelope_id"],
            authentication_results=data["authentication_results"],
            delivery_results=data["delivery_result"],
            source_ip_address=data["source"]["ip_address"],
            source_country=data["source"]["country"],
            source_reverse_dns=data["source"]["reverse_dns"],
            source_base_domain=data["source"]["base_domain"],
            authentication_mechanisms=data["authentication_mechanisms"],
            auth_failure=data["auth_failure"],
            dkim_domain=data["dkim_domain"],
            original_rcpt_to=data["original_rcpt_to"],
            sample=sample,
            using=self.client,
        )

        forensic_doc.meta.index = index
        forensic_doc.save()
        return

    ## Internal Methods
    ## -------------------------------------------------------------------------
    def _get_index_name(self, base: str, date: datetime.datetime) -> str:
        """Format an index based on our settings

        Args:
            base: base index name
            date: date to use to generate index
        """
        if self.config.monthly_indexes:
            index_date = date.strftime("%Y-%m")
        else:
            index_date = date.strftime("%Y-%m-%d")

        return f"{base}-{index_date}"

    def _create_indexes(self, names: list[str] | str) -> None:
        """
        Create OpenSearch indexes

        Args:
            names: A list of index names
        """
        if isinstance(names, str):
            names = [names]

        for name in names:
            index = Index(name, using=self.client)
            if not index.exists():
                self.debug(f"Creating index: {name}")
                index.settings(
                    number_of_shards=self.config.number_of_shards,
                    number_of_replicas=self.config.number_of_replicas,
                )
                index.create()
        return

    def _migrate_indexes(
        self, aggregate_indexes: list[str] | None = None, forensic_indexes: list[str] | None = None
    ) -> None:
        """
        Updates index mappings

        Args:
            aggregate_indexes (list): A list of aggregate index names
            forensic_indexes (list): A list of forensic index names
        """

        if aggregate_indexes is None:
            aggregate_indexes = []
        if forensic_indexes is None:
            forensic_indexes = []

        ## Migrate aggregate report indexes
        for aggregate_index_name in aggregate_indexes:
            if not Index(aggregate_index_name, using=self.client).exists():
                continue

            aggregate_index = Index(aggregate_index_name, using=self.client)
            doc = "doc"
            fo_field = "published_policy.fo"
            fo = "fo"
            fo_mapping = aggregate_index.get_field_mapping(fields=[fo_field])
            fo_mapping = fo_mapping[list(fo_mapping.keys())[0]]["mappings"]
            if doc not in fo_mapping:
                continue

            fo_mapping = fo_mapping[doc][fo_field]["mapping"][fo]
            fo_type = fo_mapping["type"]
            if fo_type == "long":
                self.info(f"Migrating {aggregate_index_name}")
                new_index_name = f"{aggregate_index_name}-v{self.INDEX_VERSION}"
                body = {
                    "properties": {
                        "published_policy.fo": {
                            "type": "text",
                            "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                        }
                    }
                }
                Index(new_index_name, using=self.client).create()
                Index(new_index_name, using=self.client).put_mapping(doc_type=doc, body=body)
                self.client.reindex(aggregate_index_name, new_index_name)
                Index(aggregate_index_name, using=self.client).delete()

        ## Migrate foresnic report indexes
        # nothingtodohere.png
        return


## Config Classes
## -----------------------------------------------------------------------------
class OpenSearchConfig(BaseConfig):
    """OpenSearch Config"""

    client: OpenSearchClientConfig
    index_suffix: Union[str, None] = None
    index_prefix: str = ""
    monthly_indexes: bool = True
    number_of_shards: int = 1
    number_of_replicas: int = 0
    on_duplicate: Literal["discard"] = "discard"  # TODO: implement update logic and add


class OpenSearchClientConfig(BaseModel):
    """OpenSearch Client Config"""

    hosts: Union[str, List[str]]
    ssl: bool = False
    cert_path: Union[str, None] = None
    username: Union[str, None] = None
    password: Union[str, None] = None
    api_key: Union[str, None] = None
    timeout: int = 60


## OpenSearch Document Classes
## -----------------------------------------------------------------------------
class _PolicyOverride(InnerDoc):
    type = Text()
    comment = Text()


class _PublishedPolicy(InnerDoc):
    domain = Text()
    adkim = Text()
    aspf = Text()
    p = Text()
    sp = Text()
    pct = Integer()
    fo = Text()


class _DKIMResult(InnerDoc):
    domain = Text()
    selector = Text()
    result = Text()


class _SPFResult(InnerDoc):
    domain = Text()
    scope = Text()
    results = Text()


class _AggregateReportDoc(Document):
    # class Index:  # pylint: disable=too-few-public-methods
    #     name = "dmarc_aggregate"

    xml_schema = Text()
    org_name = Text()
    org_email = Text()
    org_extra_contact_info = Text()
    report_id = Text()
    date_range = Date()
    date_begin = Date()
    date_end = Date()
    errors = Text()
    published_policy = Object(_PublishedPolicy)
    source_ip_address = Ip()
    source_country = Text()
    source_reverse_dns = Text()
    source_base_domain = Text()
    source_type = Text()
    source_name = Text()
    message_count = Integer
    disposition = Text()
    dkim_aligned = Boolean()
    spf_aligned = Boolean()
    passed_dmarc = Boolean()
    policy_overrides = Nested(_PolicyOverride)
    header_from = Text()
    envelope_from = Text()
    envelope_to = Text()
    dkim_results = Nested(_DKIMResult)
    spf_results = Nested(_SPFResult)

    def add_policy_override(self, type_, comment):
        self.policy_overrides.append(_PolicyOverride(type=type_, comment=comment))

    def add_dkim_result(self, domain, selector, result):
        self.dkim_results.append(_DKIMResult(domain=domain, selector=selector, result=result))

    def add_spf_result(self, domain, scope, result):
        self.spf_results.append(_SPFResult(domain=domain, scope=scope, result=result))

    def save(self, *args, **kwargs):
        self.passed_dmarc = False
        self.passed_dmarc = self.spf_aligned or self.dkim_aligned

        return super().save(*args, **kwargs)


class _EmailAddressDoc(InnerDoc):
    display_name = Text()
    address = Text()


class _EmailAttachmentDoc(Document):
    filename = Text()
    content_type = Text()
    sha256 = Text()


class _ForensicSampleDoc(InnerDoc):
    raw = Text()
    headers = Object()
    headers_only = Boolean()
    to = Nested(_EmailAddressDoc)
    subject = Text()
    filename_safe_subject = Text()
    _from = Object(_EmailAddressDoc)
    date = Date()
    reply_to = Nested(_EmailAddressDoc)
    cc = Nested(_EmailAddressDoc)
    bcc = Nested(_EmailAddressDoc)
    body = Text()
    attachments = Nested(_EmailAttachmentDoc)

    def add_to(self, display_name, address):
        self.to.append(_EmailAddressDoc(display_name=display_name, address=address))

    def add_reply_to(self, display_name, address):
        self.reply_to.append(_EmailAddressDoc(display_name=display_name, address=address))

    def add_cc(self, display_name, address):
        self.cc.append(_EmailAddressDoc(display_name=display_name, address=address))

    def add_bcc(self, display_name, address):
        self.bcc.append(_EmailAddressDoc(display_name=display_name, address=address))

    def add_attachment(self, filename, content_type, sha256):
        self.attachments.append(
            _EmailAttachmentDoc(filename=filename, content_type=content_type, sha256=sha256)
        )


class _ForensicReportDoc(Document):
    # class Index:  # pylint: disable=too-few-public-methods
    #     name = "dmarc_forensic"

    feedback_type = Text()
    user_agent = Text()
    version = Text()
    original_mail_from = Text()
    arrival_date = Date()
    domain = Text()
    original_envelope_id = Text()
    authentication_results = Text()
    delivery_results = Text()
    source_ip_address = Ip()
    source_country = Text()
    source_reverse_dns = Text()
    source_authentication_mechanisms = Text()
    source_auth_failures = Text()
    dkim_domain = Text()
    original_rcpt_to = Text()
    sample = Object(_ForensicSampleDoc)
