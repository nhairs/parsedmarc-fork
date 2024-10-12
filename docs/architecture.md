# Architecture

## About parsedmarc-fork

Parsedmarc-fork contains the same functionality of parsedmarc but the main application has been completely rewritten to use a "streaming" model for handling reports. As this required a full rewrite of the main application a number of new internal interfaces have been added to support adding other data sources/destinations with minimal code changes to the main application.

We introduce the following interfaces:

- **Source**: things that produce reports.
- **Sink**: things that receive reports.
- **Job**: a container for tracking a report's lifecycle through the application.

At a high level the application operates as follows:

1. Initialise and read configuration
2. Create and initialise all configured sources and sinks
3. Create a `SourceWorker` thread for each source.
  - This worker will get new jobs from the source and send them to a central "inbound" queue.
4. Create a `SinkWorker` thread for each sink
  - This worker receives jobs on a queue and passes them to the sink.
  - The worker then passes the job and it's completion status (success/error) to a central "outbound" queue.
5. Create an `InboundWorker` thread
  - This worker takes jobs from the inbound queue and fans out the job to each `SinkWorker`
6. Create an `OutboundWorker` thread
  - This worker receives completed jobs then passes the completed job to it's source for acknowledgement.
  - This allows sources to decide how to handle reports based on status as well as have "in-flight" jobs.
  - In particular this opens up to new types of works such as those based on queues (e.g. RabbitMQ, AWS SQS).
  - It also allows us to delay things like archiving/deleting messages until we know they have been stored (email or file based sources).
7. The main thread does nothing but wait for a shutdown signal. Once received it gracefully shuts down all the works and sends unhandled jobs (i.e. status=cancelled) back to the sources to be handled.

A few other things to note with the application/interfaces are:

- Through the use of [queues](https://docs.python.org/3/library/queue.html) we can limit the number of in-flight jobs ensuring a fairly predictable memory footprint even when dealing with a large number of messages.
- The application loads sources/sinks based on an importable name. This means that sources/sinks can be added simply by creating the appropriate class - no further code required.
  - This also means that we can load external classes, allowing users of the application to load their own custom sources/sinks without forking the project and requiring them to be in the main project. This is already implemented and held behind a CLI flag.
- The configuration file allows for multiple sources/sinks to be configured using the same class. That is to say you could configure many IMAP sources and many ElasticSearch sinks and have them all operate with their won config.
- Configuration for sources/sinks are defined using pydantic and attached to classes using type annotations. This allows us to validate configuration before creating objects and for type checking/auto-completion during development.
  - This is also why there is no application level changes to add a new source/sink to the application apart from creating the class.
- Because the application is designed as a long lived process it can be managed through existing service/daemon tools such as systemd.
