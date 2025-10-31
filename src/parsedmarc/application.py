### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
from copy import deepcopy
import importlib
import itertools
import logging
import queue as q
import threading
import time
from typing import Any, Sequence

# Installed
import pillar.application
import pillar.logging

# Local
from .const import AppState
from .parser import ReportParser
from .sink.base import Sink
from .source.base import Job, JobStatus, Source


### FUNCTIONS
### ============================================================================
def main():
    app = StreamApplication()
    app.run()
    return app


### CLASSES
### ============================================================================
class StreamApplication(pillar.application.Application):
    """ParseDMARC application with streaming implementation.

    This is a fork of the original ParseDMARC project.

    *New in 9.0*.
    """

    application_name = "parsedmarcd"

    logging_manifest = pillar.application.LoggingManifest(
        additional_namespaces=["mailparser"],
    )

    default_config = {
        "parser": {},
        "sources": {},
        "sinks": {},
        "app": {
            "queue_max_length": 100,
        },
    }

    parser: ReportParser
    sources: Sequence[Source]
    source_workers: Sequence[SourceWorker]
    sinks: Sequence[Sink]
    sink_workers: Sequence[SinkWorker]
    inbound_worker: InboundWorker
    outbound_worker: OutboundWorker
    workers: list[Worker]

    def get_argument_parser(self):
        parser = super().get_argument_parser()
        parser.add_argument(
            "--allow-external", action="store_true", help="Allow loading external source and sinks"
        )
        return parser

    ## Setup
    ## -------------------------------------------------------------------------
    def make_source(self, name: str, config: dict[str, Any]) -> Source:
        config = deepcopy(config)
        class_path = config.pop("class")

        if class_path.startswith("."):
            class_path = "parsedmarc.source" + class_path
        class_ = self.load_object(class_path)

        if not issubclass(class_, Source):
            raise ValueError(f"{class_} is not a Source")

        source = class_(
            name,
            self.parser,
            config,
        )
        return source

    def make_sink(self, name: str, config: dict[str, Any]) -> Sink:
        config = deepcopy(config)
        class_path = config.pop("class")

        if class_path.startswith("."):
            class_path = "parsedmarc.sink" + class_path
        class_ = self.load_object(class_path)

        if not issubclass(class_, Sink):
            raise ValueError(f"{class_} is not a Sink")

        sink = class_(
            name,
            config,
        )
        return sink

    def load_object(self, name: str) -> Any:
        if not name.startswith("parsedmarc.") and not self.args.allow_external:
            raise ValueError(
                f"Cannot load external object {name!r}, external loading disabled. Enable with --allow-external"
            )
        module, path = name.split(":")
        obj = importlib.import_module(module)
        for attr in path.split("."):
            obj = getattr(obj, attr)
        return obj

    ## Main
    ## -------------------------------------------------------------------------
    def main(self) -> int | None:
        # pylint: disable=broad-exception-caught
        # Ignore catching Exception as this method is designed to be very robust

        ## Setup
        ## ---------------------------------------------------------------------
        self.info("parsedmarcd starting")
        error = False

        ## Create Parser
        self.debug("loading parser")
        try:
            self.parser = ReportParser(**self.config["parser"])
        except Exception:
            self.critical("Failed to load parser", exc_info=True)
            error = True

        ## Create Sources
        self.debug("loading sources")
        self.sources = []
        for name, config in self.config["sources"].items():
            self.vdebug(f"loading source {name}")
            try:
                source = self.make_source(name, config)
                if source.config.enabled:
                    self.sources.append(source)
                else:
                    self.debug(f"skipping disabled source {name}")
            except Exception:
                error = True
                self.critical(f"Failed to load source {name}", exc_info=True)

        ## Create Sinks
        self.debug("loading sinks")
        self.sinks = []
        for name, config in self.config["sinks"].items():
            self.vdebug(f"loading sink {name}")
            try:
                sink = self.make_sink(name, config)
                if sink.config.enabled:
                    self.sinks.append(sink)
                else:
                    self.debug(f"Skipping disabled sink {name}")
            except Exception:
                error = True
                self.critical(f"Failed to load sink {name}", exc_info=True)

        ## Check create actions
        if error:
            self.critical("Failed to initialise")
            return 1

        self.info(f"Loaded sources: {', '.join(map(str, self.sources))}")
        self.info(f"Loaded sinks: {', '.join(map(str, self.sinks))}")

        if not self.sources:
            self.critical("Must configure at least one source")
            return 1
        if len(self.sinks) != 1:
            self.critical("Must configure exactly one sink")
            return 1

        ## Initialise sources and sinks
        _setup_complete: Sequence[Source | Sink] = []
        for obj in self.sources + self.sinks:
            try:
                self.vdebug(f"Setting up {obj}")
                obj.setup()
            except Exception:
                self.critical(f"Failed to setup {obj}, shutting down", exc_info=True)
                self._shutdown_sources_and_sinks(_setup_complete)
                return 1

        del _setup_complete

        ## Create Workers
        queue_max = self.config["app"]["queue_max_length"]

        try:
            self.debug("Creating source workers")
            source_queue: q.Queue[Job] = q.Queue(maxsize=queue_max)

            self.source_workers = []
            for source in self.sources:
                self.vvdebug(f"Creating worker for {source}")
                self.source_workers.append(SourceWorker(source, source_queue))

            self.debug("Creating sink workers")
            self.sink_workers = []
            for sink in self.sinks:
                self.vvdebug(f"Creating worker for {sink}")
                self.sink_workers.append(SinkWorker(sink, q.Queue(queue_max), q.Queue()))

            self.debug("Creating inbound worker")
            self.inbound_worker = InboundWorker(source_queue, self.sink_workers)

            self.debug("Creating outbout worker")
            self.outbound_worker = OutboundWorker(self.sink_workers)

        except Exception:
            self.critical("Failed to create all workers", exc_info=True)
            self._shutdown_sources_and_sinks()
            return 1

        # Note: worker order matters here as this is the shutdown order
        self.workers = (
            self.source_workers + [self.inbound_worker] + self.sink_workers + [self.outbound_worker]
        )

        ## Create Hooks
        # TODO

        ## Start workers
        self.info("Starting workers")
        try:
            for worker in self.workers:
                self.debug(f"Starting {worker}")
                worker.start()
        except Exception:
            self.critical("Failed to start workers", exc_info=True)
            self._shutdown_workers()
            self._shutdown_sources_and_sinks()
            return 1

        ## Wait for shutdown
        while True:
            try:
                time.sleep(0.5)
            except KeyboardInterrupt:
                self.info("Received KeyboardInterrupt, shutting down")
                break

        self._shutdown_workers()
        self._shutdown_sources_and_sinks()

        self.info("shutdown complete")
        return None

    def _shutdown_sources_and_sinks(self, objects: Sequence[Source | Sink] | None = None) -> None:
        self.debug("Shutting down sources and sinks")
        if objects is None:
            objects = list(itertools.chain(self.sources, self.sinks))

        for obj in objects:
            try:
                self.vdebug(f"Shutting down {obj}")
                obj.shutdown()
            except Exception:  # pylint: disable=broad-exception-caught
                self.error(f"Failed to cleanup {obj}", exc_info=True)
                continue
        return

    def _shutdown_workers(self, workers: Sequence[Worker] | None = None) -> None:
        self.debug("Shutting down workers")
        if workers is None:
            workers = self.workers

        for worker in workers:
            self.vdebug(f"Sending shutdown to {worker}")
            worker.set_shutdown()

        self.debug("Waiting for workers to shutdown")
        for worker in workers:
            self.vdebug(f"Joining {worker}")
            worker.thread.join()
        return


## Workers
## -----------------------------------------------------------------------------
class Worker(pillar.logging.LoggingMixin):
    """Base class for workers.

    *New in 9.0*.
    """

    thread: threading.Thread
    _state: AppState
    _shutdown: bool

    SLEEP_TIME = 1

    def __init__(self) -> None:
        raise NotImplementedError("Child classes must implement __init__")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}"

    @property
    def state(self) -> AppState:
        return self._state

    def start(self) -> None:
        if self.state != AppState.SHUTDOWN:
            raise RuntimeError("Worker is not shutdown")
        self._state = AppState.SETTING_UP
        try:
            self.vdebug("Setting up")
            self.setup()

            self.vdebug("Starting thread")
            self._shutdown = False
            self.thread = threading.Thread(target=self._main, daemon=False)
            self.thread.start()
            self.vdebug("Thread started")
            self._state = AppState.RUNNING
        except Exception:  # pylint: disable=broad-exception-caught
            self._state = AppState.SETUP_ERROR
            self.error("Failed to start", exc_info=True)
            raise
        return

    def set_shutdown(self) -> None:
        if self.state != AppState.RUNNING:
            raise RuntimeError("Worker is not running")
        self._shutdown = True
        return

    def _main(self) -> None:
        while True:
            try:
                self.main()
            except StopIteration:
                if not self._shutdown:
                    self.info("Worker has run out of work, shutting down")
                    self._shutdown = True
                self.debug("recevied shutdown, breaking loop")
                break

        # Shutdown detected
        self._state = AppState.SHUTTING_DOWN
        self.debug("Shutting down")
        try:
            self.cleanup()
        except Exception:  # pylint: disable=broad-exception-caught
            self._state = AppState.SHUTDOWN_ERROR
            self.error("Failed to shutdown", exc_info=True)
            raise
        self._state = AppState.SHUTDOWN
        return

    def record_success(self) -> None:
        return

    def record_error(self) -> None:
        return

    def sleep(self, sleep_time: int | None = None) -> None:
        time.sleep(sleep_time or self.SLEEP_TIME)
        return

    ## Child Classes
    ## -------------------------------------------------------------------------
    def setup(self) -> None:
        return

    def cleanup(self) -> None:
        return

    def main(self) -> None:
        return


# Source
# ..............................................................................
class SourceWorker(Worker):
    """Source Worker

    *New in 9.0*.
    """

    SLEEP_TIME = 30  # Override default as sources may not have jobs very often

    def __init__(self, source: Source, queue: q.Queue[Job]) -> None:
        """
        Args:
            source: Source for this worker to make jobs from
            queue: output queue to send jobs to
        """
        self.source = source
        self.queue = queue
        self._shutdown = False
        self._state = AppState.SHUTDOWN

        self.logger = logging.getLogger(
            pillar.logging.get_logger_name_for_instance(self) + f".i-{source.name}"
        )
        return

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.source})"

    def main(self) -> None:
        # pylint: disable=broad-exception-caught
        # Ignore catching Exception as this method is designed to be very robust

        try:
            if self._shutdown:
                raise StopIteration()

            if self.queue.full():
                self.vdebug("queue full, sleeping")
                self.sleep()
                return

            job = self.source.get_job()

            if job is None:
                self.vvdebug("No jobs available, sleeping")
                self.sleep()
                return

            self.vvdebug(f"Got job: {job}")
            self.queue.put(job)
            self.vvdebug(f"Sent job: {job}")
            self.record_success()

        except StopIteration:
            raise

        except Exception:
            self.error("Uncaught exception", exc_info=True)
            self.record_error()
        return


# Sink
# ..............................................................................
class SinkWorker(Worker):
    """Sink Worker

    *New in 9.0*.
    """

    def __init__(
        self, sink: Sink, in_queue: q.Queue[Job], out_queue: q.Queue[tuple[Job, JobStatus]]
    ) -> None:
        """
        Args:
            sink: sink to send jobs to
            in_queue: jobs to store
            out_queue: response to jobs
        """
        self.sink = sink
        self.in_queue = in_queue
        self.out_queue = out_queue
        self._shutdown = False
        self._state = AppState.SHUTDOWN

        self.logger = logging.getLogger(
            pillar.logging.get_logger_name_for_instance(self) + f".i-{sink.name}"
        )
        return

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.sink})"

    def main(self) -> None:
        # pylint: disable=broad-exception-caught
        # Ignore catching Exception as this method is designed to be very robust

        job: Job | None = None
        try:
            job = self.in_queue.get(block=False)
            self.sink.process_report(job.report)
            self.out_queue.put((job, JobStatus.SUCCESS))
            self.record_success()

        except q.Empty:
            if self._shutdown:
                raise StopIteration()  # pylint: disable=raise-missing-from
            self.vvdebug("No jobs available, sleeping")
            self.sleep()
            return

        except Exception:
            self.error("Uncaught exception", exc_info=True)
            if job is not None:
                self.out_queue.put((job, JobStatus.ERROR))
            self.record_error()
        return


# Inbound
# ..............................................................................
class InboundWorker(Worker):
    """Worker that handles passing jobs from sources to all sinks

    *New in 9.0*.
    """

    def __init__(self, queue: q.Queue[Job], sink_workers: list[SinkWorker]) -> None:
        self.queue = queue
        self.sink_workers = list(sink_workers)

        self._shutdown = False
        self._state = AppState.SHUTDOWN

        self.logger = logging.getLogger(pillar.logging.get_logger_name_for_instance(self))
        return

    def main(self) -> None:
        # pylint: disable=broad-exception-caught
        # Ignore catching Exception as this method is designed to be very robust

        try:
            job = self.queue.get(block=False)
            for worker in self.sink_workers:
                worker.in_queue.put(job)
            self.record_success()

        except q.Empty:
            if self._shutdown:
                raise StopIteration()  # pylint: disable=raise-missing-from
            self.vvdebug("No jobs available, sleeping")
            self.sleep()
            return

        except Exception:
            self.error("Uncaught exception", exc_info=True)
            self.record_error()
        return


# Outbound
# ..............................................................................
class OutboundWorker(Worker):
    """Worker than handles passing completed jobs from sinks to sources

    *New in 9.0*.
    """

    def __init__(self, sink_workers: list[SinkWorker]) -> None:
        # Current implementation only supports one SinkWorker
        if len(sink_workers) != 1:
            raise RuntimeError("Must provide exactly one SinkWorker")

        self.sink_workers = list(sink_workers)
        self._queue = sink_workers[0].out_queue

        self._shutdown = False
        self._state = AppState.SHUTDOWN

        self.logger = logging.getLogger(pillar.logging.get_logger_name_for_instance(self))
        return

    def main(self) -> None:
        # pylint: disable=broad-exception-caught
        # Ignore catching Exception as this method is designed to be very robust

        try:
            job, job_status = self._queue.get(block=False)
            job.source.ack_job(job, job_status)
            self.record_success()

        except q.Empty:
            if self._shutdown:
                raise StopIteration()  # pylint: disable=raise-missing-from
            self.vvdebug("No jobs available, sleeping")
            self.sleep()
            return

        except Exception:
            self.error("Uncaught exception", exc_info=True)
            self.record_error()
        return
