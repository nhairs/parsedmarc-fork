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



### Migrating Your Config

This section documents each item in the `parsedmarc` config and how to move it to the `parsedmarcd` config.

All heading are config options are defined using their original `parsedmarc` name as they were in version `8.15.0`.

!!! warning "TODO"
    list all config items within each section, don't just say "use this".

#### `general`

`save_aggregate`: not supported - no comparable option.

`save_forensic`: not supported - no comparable option.

`save_smtp_tls`: not supported - [GitHub Issue #5](https://github.com/nhairs/parsedmarc-fork/issues/5)
`strip_attachment_payloads`: moved to `parser.strip_attachment_payloads`

`output`: not supported - [GitHub Issue #24](https://github.com/nhairs/parsedmarc-fork/issues/24)
`aggregate_json_filename`: not supported - see `output` above.

`forensic_json_filename`: not supported - see `output` above.

`ip_db_path`: moved to `parser.ip_db_path`

`offline`: moved to `parser.offline`

`always_use_local_files`: not supported - [GitHub Issue #10](https://github.com/nhairs/parsedmarc-fork/issues/10)

`local_reverse_dns_map_path`: not supported - [GitHub Issue #10](https://github.com/nhairs/parsedmarc-fork/issues/10)

`nameservers`: moved to `parser.nameservers.[]`

`dns_timeout`: moved to `parse.dns_timeout`

`debug`: not supported - use the `--verbose`/`-v` commandline option instead.

`silent`: not supported - no comparable option.

`log_file`: not supported - use the `--log-dir` commadline option instead.

`n_procs`: not supported - no comparable option.

#### `mailbox`

Use the `.email:MailboxConnectionSource` Source.

#### `imap`

Use the `.email:Imap` Source.

#### `msgraph`

Use the `.email.MicosoftGraph` Source.

#### `elasticsearch`

Use the `.elasticsearch:Elasticsearch` Sink.

#### `opensearch`

Not supported - [GitHub issue #6](https://github.com/nhairs/parsedmarc-fork/issues/6)

#### `splunk_hec`

Not supported - [GitHub Issue #27](https://github.com/nhairs/parsedmarc-fork/issues/27)

#### `kafka`

Use the `.kafka:Kafka` Sink.

#### `smtp`

Not supported - [GitHub Issue #29](https://github.com/nhairs/parsedmarc-fork/issues/29)

#### `s3`

Use the `.aws:S3` Sink.

#### `syslog`

Use the `.syslog:Syslog` Sink.

#### `gmail_api`

Use the `.email:Google` Source.

#### `log_analytics`

Use the `.azure:LogAnalytics` Sink.

#### `gelf`

Not supported - [GitHub Issue #13](https://github.com/nhairs/parsedmarc-fork/issues/13)
