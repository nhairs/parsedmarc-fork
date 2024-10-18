# Migrating to `parsedmarcd`

In version `9.0.0` (TBC) ParseDMARC introduced a new application for processing reports and although there are many benefit of this new application it is incompatible with the existing CLI application. To avoid confusion we will use the specific application name when talking about ParseDMARC:

- `parsedmarc` is the original CLI application that you know and love.
- `parsedmarcd` is the new application.

## Application Architecture

The primary difference between the two applications is in how they pass reports from some source to some destination.

`parsedmarc` was designed to run on batches of reports with all reports being collected and processed from some source before being sent to some destination. This meant to process the continous stream of DMARC reports you'd have to either run `parsedmarc` on a timer (e.g. as a CRON job), or if you were collecting reports directly from an email mailbox run `parsedmarc` using `--watch` to check for new emails. This mode of operation did allow for reporting on all reports at once (e.g. as a CSV attachment to an email) as all reports were processed at the same time.

In comparison `parsedmarcd` is designed to operate as a service on a stream of reports with reports being sent to the destinations as they come available. Once a report is processed, `parsedmarcd` will notifiy the source with the status (e.g. `SUCCESS`, `ERROR`) so that the source can take appropriate action (e.g. deleting the email on `SUCCESS`, or sending it to a dead-letter-queue on `ERROR`). This streaming model with feedback allows for more robust processing of reports and lower memory consumption.

Another key difference is that in `parsedmarc` you could only provide one config for each type of section. This meant that if you wanted to have the same item configured multiple time (i.e. because you had multiple IMAP mailboxes to monitor), then you would have to run `parsedmarc` multiple times. With `parsedmarcd` items use a unique user-defined name allowing you to repeat the same type of item with different configuration.

You can find the full details about the [new application architecture here](architecture.md).

## Running `parsedmarcd`

`parsedmarcd` is designed to run as a service and as such most configuration is done through configuration files. For the purposes of this guide know that you can run the application using `parsedmarcd --config /path/to/config.yml` and stop it using ++ctrl+c++.

For deeper information about configuring and running `parsedmarcd` see:

- [Quickstart](quickstart.md)
- [Installing ParseDMARC](installing.md)
- [Configuring ParseDMARC](configuration.md)
- [Running ParseDMARC](running.md)

### Migrating Existing CLI arguments

`file_path`: not supported - [GitHub Issue #24](https://github.com/nhairs/parsedmarc-fork/issues/24).

`--help`/`-h`: no changes.

`--config-file`/`-c`: moved to `--config`. For more information see [Configure `parsedmarcd` below](#configuring-parsedmarc).

`--strip-attachment-payloads`: not supported - use config `parser.strip_attachment_payloads` instead.

`--output`/`-o`: not supported - [GitHub Issue #24](https://github.com/nhairs/parsedmarc-fork/issues/24).

`--aggregate-json-filename`: not supported - [GitHub Issue #24](https://github.com/nhairs/parsedmarc-fork/issues/24).

`--forensic-json-filename`: not supported - [GitHub Issue #24](https://github.com/nhairs/parsedmarc-fork/issues/24).

`--aggregate-csv-filename`: not supported - [GitHub Issue #24](https://github.com/nhairs/parsedmarc-fork/issues/24).

`--forensic-csv-filename`: not supported - [GitHub Issue #24](https://github.com/nhairs/parsedmarc-fork/issues/24).

`--nameservers`/`-n`: not supported - use config `parser.nameservers` instead.

`--dns-timeout`/`-t`: not supported - use config `parser.dns_timeout` instead.

`--offline`: not supported - use config `parser.offline` instead.

`--silent`/`-s`: not supported.

`--verbose`: now supports using `-v` and up to 3 levels of verbosity (e.g. `-vvv`).

`--debug`: not supported - use `--verbose`/`-v` instead.

`--log-file`: not supported - use `--log-dir` instead.

`--version`/`-v`: `--version` is unchanged. `-v` no longer prints the version - it instead is used for `--verbose`.


## Configuring `parsedmarcd`

`parsedmarcd` uses YAML (or JSON) for configuration. This allows for much richer configuration but also requires migrating your old config to the new format.

At this point it important to make sure you understand some key terminology:

- **Source**: something that collects or otherwise produces reports for processing.
- **Sink**: something that receives parsed reports.

!!! warning
    Currently `parsedmarcd` only supports have one sink configured. This is a known drawback and will be changed in the future.

```yaml title="example-config.yml"
parser:
  nameservers:
    - 1.1.1.1
    - 8.8.8.8

sources:
  aws-ses-dev:
    class: .aws:SimpleEmailService
    session:
      profile_name: my-dev-profile
    queue_name: my-dev-dmarc-receiving

sinks:
  elasticsearch:
    class: .elasticsearch:Elasticsearch
    client:
      hosts: localhost:9200
      username: elastic
      password: SECRET
```

Each source and sink is configured by giving it a unique name and then providing its `class` and then any other required configuration.

!!! tip
    Because each source and sink is given a unique name you can define the same class multiple times.



## Migrating Your Config

This section documents each item in the `parsedmarc` config and how to move it to the `parsedmarcd` config.

All heading are config options are defined using their original `parsedmarc` name as they were in version `8.15.0`.


### `general`

- `save_aggregate`: not supported - no comparable option.
- `save_forensic`: not supported - no comparable option.
- `save_smtp_tls`: not supported - [GitHub Issue #5](https://github.com/nhairs/parsedmarc-fork/issues/5).
- `strip_attachment_payloads`: moved to `parser.strip_attachment_payloads`.
- `output`: not supported - [GitHub Issue #24](https://github.com/nhairs/parsedmarc-fork/issues/24).
- `aggregate_json_filename`: not supported - [GitHub Issue #24](https://github.com/nhairs/parsedmarc-fork/issues/24).
- `forensic_json_filename`: not supported - [GitHub Issue #24](https://github.com/nhairs/parsedmarc-fork/issues/24).
- `ip_db_path`: moved to `parser.ip_db_path`
- `offline`: moved to `parser.offline`.
- `always_use_local_files`: not supported - [GitHub Issue #10](https://github.com/nhairs/parsedmarc-fork/issues/10).
- `local_reverse_dns_map_path`: not supported - [GitHub Issue #10](https://github.com/nhairs/parsedmarc-fork/issues/10).
- `nameservers`: moved to `parser.nameservers`.
- `dns_timeout`: moved to `parse.dns_timeout`.
- `debug`: not supported - use the `--verbose`/`-v` commandline option instead.
- `silent`: not supported - no comparable option.
- `log_file`: not supported - use the `--log-dir` commadline option instead.
- `n_procs`: not supported - no comparable option.


### `mailbox`

Use a `.email:MailboxConnectionSource` Source.

- `reports_folder`: no changes.
- `archive_folder`: no changes.
- `watch`: not supported - no comparable option.
- `delete`: not supported - use `mode: "delete"` instead.
- `test`: not supported - use `mode: "test"` instead.
- `batch_size`: not supported - no comparable option.
- `check_timeout`: not supported - no comparable option.


### `imap`

Use a `.email:Imap` Source.

- `host`: no changes.
- `port`: now optional and will select the appropriate default port based on SSL/TLS settings.
- `ssl`: no changes.
- `skip_certificate_verification`: moved to `verify_ssl`.
- `user`: moved to `username`.
- `password`: no changes.


### `msgraph`

Use a `.email.MicosoftGraph` Source.

- `auth_method`: no changes.
- `user`: moved to `username`.
- `password`: no changes.
- `client_id`: no changes.
- `client_secret`: no changes.
- `tenant_id`: no changes.
- `mailbox`: no changes.
- `token_file`: no changes.
- `allow_unencrypted_storage`: no changes.


### `elasticsearch`

Use a `.elasticsearch:Elasticsearch` Sink.

- `hosts`: moved to `client.hosts`.
- `user`: moved to `client.username`.
- `password`: moved to `client.password`.
- `apiKey`: moved to `client.api_key`.
- `ssl`: moved to `client.ssl`.
- `timeout`: moved to `client.timeout`.
- `cert_path`: moved to `client.cert_path`.
- `index_suffix`: no changes.
- `index_prefix`: not supported - [GitHub Issue #12](https://github.com/nhairs/parsedmarc-fork/issues/12).
- `monthly_indexes`: no changes.
- `number_of_shards`: no changes.
- `number_of_replicas`: no changes.


### `opensearch`

Use a `.opensearch:OpenSearch` Sink.

- `hosts`: moved to `client.hosts`.
- `user`: moved to `client.username`.
- `password`: moved to `client.password`.
- `apiKey`: moved to `client.api_key`.
- `ssl`: moved to `client.ssl`.
- `timeout`: moved to `client.timeout`.
- `cert_path`: moved to `client.cert_path`.
- `index_suffix`: no changes.
- `index_prefix`: no changes.
- `monthly_indexes`: no changes.
- `number_of_shards`: no changes.
- `number_of_replicas`: no changes.

### `splunk_hec`

Use a `.splunk:Splunk` Sink.

- `url`: moved to `client.url`.
- `token`: moved to `client.token`.
- `index`: no changes.
- `skip_certification_verification`: moved to `client.verify_ssl`.


### `kafka`

Use a `.kafka:Kafka` Sink.

- `hosts`: moved to `client.hosts`.
- `user`: moved to `client.username`.
- `password`: moved to `client.password`.
- `ssl`: moved to `client.ssl`.
- `skip_certificate_verification`: moved to `client.verify_ssl`.
- `aggregate_topic`: moved to `aggregate_report_topic`.
- `forensic_topic`: moved to `forensic_report_topic`.


### `smtp`

Not supported - [GitHub Issue #29](https://github.com/nhairs/parsedmarc-fork/issues/29).


### `s3`

Use a `.aws:S3` Sink.

- `bucket`: no changes.
- `path`: moved to `path_prefix`.
- `region_name`: moved to `client.region_name`.
- `endpoint_url`: moved to `client.endpoint_url`.
- `access_key_id`: moved to `client.aws_access_key_id`.
- `secret_access_key`: moved to `client.aws_secret_access_key`.


### `syslog`

Use a `.syslog:Syslog` Sink.

- `server`: moved to `syslog_host`.
- `port`: moved to `syslog_port`.


### `gmail_api`

Use a `.email:Google` Source.

- `credentials_file`: no changes.
- `token_file`: no changes.
- `include_spam_trash`: no changes.
- `scopes`: no changes.
- `oauth2_port`: no changes.
- `paginate_messages`: not supported - [GitHub Issue #14](https://github.com/nhairs/parsedmarc-fork/issues/14).


### `log_analytics`

Use a `.azure:LogAnalytics` Sink.

- `client_id`: no changes.
- `client_secret`: no changes.
- `tenant_id`: no changes.
- `dce`: moved to `data_collection_endpoint`.
- `dcr_immutable_id`: moved to `data_collection_rule_id`.
- `dcr_aggreate_stream`: moved to `aggregate_report_stream`.
- `dcr_forensic_stream`: moved to `forensic_report_stream`.
- `dcr_smtp_tls_stream`: not supported - [GitHub Issue #5](https://github.com/nhairs/parsedmarc-fork/issues/5).


### `gelf`

Not supported - [GitHub Issue #13](https://github.com/nhairs/parsedmarc-fork/issues/13).


### `webhook`

Use a `.webhook:JsonWebhook` Sink.

- `aggregate_url`: moved to `aggregate_report_url`.
- `forensic_url`: moved to `forensic_report_url`.
- `smtp_tls_url`: not supported - [GitHub Issue #5](https://github.com/nhairs/parsedmarc-fork/issues/5).
- `timeout`: moved to `http_timeout`.
