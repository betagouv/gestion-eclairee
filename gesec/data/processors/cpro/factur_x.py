from typing import IO

import pymupdf


def read_facture_x(filename: str | None = None, stream: bytes | IO[bytes] | None = None) -> bytes | None:
    with pymupdf.Document(filename=filename, stream=stream) as doc:
        if "factur-x.xml" in doc.embfile_names():
            return doc.embfile_get("factur-x.xml")
        else:
            return None
