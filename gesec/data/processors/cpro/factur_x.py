import logging
import traceback
from typing import IO

import pymupdf


logger = logging.getLogger(__name__)


def read_factur_x(filename: str | None = None, stream: bytes | IO[bytes] | None = None, log_info: str = "") -> bytes | None:
    with pymupdf.Document(filename=filename, stream=stream) as doc:
        try:
            filenames = list(doc.embfile_names())
        except AssertionError as ex:
            tb = traceback.extract_tb(ex.__traceback__)
            last_frame = tb[-1]
            logger.warning(f"Failed to get embedded file names from PDF {log_info}: {ex!r} - {last_frame.filename}:{last_frame.lineno}:{last_frame.line}")
            return None
        if "factur-x.xml" in filenames:
            return doc.embfile_get("factur-x.xml")
        else:
            return None
