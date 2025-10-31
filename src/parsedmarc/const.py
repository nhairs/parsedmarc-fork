### IMPORTS
### ============================================================================
# Future
from __future__ import annotations

# Standard Library
import enum

### CONSTANTS
### ============================================================================
## Parsing
## -----------------------------------------------------------------------------
MAGIC_ZIP = b"\x50\x4b\x03\x04"
MAGIC_GZIP = b"\x1f\x8b"
MAGIC_XML = b"\x3c\x3f\x78\x6d\x6c\x20"


## Application
## -----------------------------------------------------------------------------
class AppState(enum.Enum):
    SHUTDOWN = enum.auto()
    RUNNING = enum.auto()
    SHUTTING_DOWN = enum.auto()
    SHUTDOWN_ERROR = enum.auto()
    SETTING_UP = enum.auto()
    SETUP_ERROR = enum.auto()
