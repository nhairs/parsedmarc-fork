### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
from collections import deque
import pathlib
from typing import List, Literal

# Local
from ..const import AppState
from ..utils import MboxIterator
from .base import BaseConfig, Job, Source


### CLASSES
### ============================================================================
## One Shot
## -----------------------------------------------------------------------------
class DirectoriesAndFiles(Source):
    """Source for reading a static list of files and directories

    This is intented for "one-shot" modes. For continuous collection and archiving use
    the `DirectoryWatcher` source.

    This source will parse the following file types:

    - Mailbox: `.mbox`
    - Email: `.eml`, `.msg`

    *New in 9.0*.
    """

    config: DirectoriesAndFilesConfig

    _EXT: dict[str, Literal["email", "mbox"]] = {
        ".eml": "email",
        ".msg": "email",
        ".mbox": "mbox",
    }

    # TODO: In the future we may want to make this able to look into archives (zip, tgz, etc)

    def setup(self) -> None:
        if self._state != AppState.SHUTDOWN:
            raise RuntimeError("Source is already running")

        self._state = AppState.SETTING_UP

        try:
            self._mbox_queue: deque[str] = deque()
            self._current_mbox: MboxIterator | None = None

            self._email_queue: deque[str] = deque()

            paths = list(self.config.paths)

            while paths:
                path = pathlib.Path(paths.pop())

            if path.is_dir():
                # directory get all files
                for sub_path in map(pathlib.Path, path.rglob("*")):
                    if sub_path.is_file():
                        paths.append(str(sub_path))
            elif path.is_file():
                type_ = self._EXT.get(path.suffix)
                if type_ == "email":
                    self._email_queue.append(str(path))
                elif type_ == "mbox":
                    self._mbox_queue.append(str(path))
                else:
                    self.warning(f"Skipping unsupported file type: {path}")
            else:
                self.warning(f"Cannot process unknown object: {path}")

        except Exception:
            self._state = AppState.SETUP_ERROR
            raise

        self._state = AppState.RUNNING
        return

    def get_job(self) -> Job | None:
        if self._state not in {AppState.RUNNING, AppState.SHUTTING_DOWN}:
            raise RuntimeError("Source is not running")

        ## Parse from email queue
        if self._email_queue:
            # TODO: parse from email
            email_path = self._email_queue.popleft()
            report = self.parser.parse_report_file(email_path)
            job = Job(source=self, report=report, identifier=email_path)
            return job

        ## Parse from mbox queue
        if self._current_mbox is None and self._mbox_queue:
            self._current_mbox = MboxIterator(self._mbox_queue.popleft())

        if self._current_mbox is not None:
            try:
                message_key, message = next(self._current_mbox)
                report = self.parser.parse_report_email(message)
                job = Job(
                    source=self,
                    report=report,
                    identifier=f"{self._current_mbox.path}:{message_key}",
                )
            except StopIteration:
                # No more messages in current mbox, attempt recursion
                self._current_mbox = None
                return self.get_job()

        ## Nothing in any queue
        return None


class DirectoriesAndFilesConfig(BaseConfig):
    """Directories and Files Config

    *New in 9.0*.
    """

    paths: List[str]


## Watching
## -----------------------------------------------------------------------------
# class DirectoryWatcher(Source):
#     config: DirectoryWatcherConfig

#     def get_job(self) -> Job | None:
#         return None


# class DirectoryWatcherConfig(BaseConfig):
#     paths: list[str]
