"""Custom storage backends exposing a recursive file search.

`find_files(path, pattern)` walks `path` recursively and yields the
storage-relative paths (with `/` separators) of the files whose full path
matches the regex `pattern`. Directories are never yielded, and on S3 folder
markers (keys ending with `/`) are ignored. The starting path goes through
Django's `safe_join` (`self.path` on the filesystem, `_normalize_name` on S3).
The yield order is implementation-dependent and not guaranteed.
"""

import os
import re
from collections.abc import Iterator

from django.core.files.storage import FileSystemStorage as DjangoFileSystemStorage

from storages.backends.s3 import S3Storage as DjangoStoragesS3Storage
from storages.utils import clean_name


class FileSystemStorage(DjangoFileSystemStorage):
    """Filesystem storage with a recursive regex search based on `os.walk`."""

    def find_files(self, path: str, pattern: str | re.Pattern) -> Iterator[str]:
        regex = re.compile(pattern) if isinstance(pattern, str) else pattern
        for dirpath, _, filenames in os.walk(self.path(path)):
            for filename in filenames:
                relative = os.path.relpath(os.path.join(dirpath, filename), self.location).replace(os.sep, "/")
                if regex.search(relative):
                    yield relative


class S3Storage(DjangoStoragesS3Storage):
    """S3 storage with a recursive regex search over a single paginated flat listing.

    One `list_objects_v2` sweep (no `Delimiter`) replaces the `1 + N` sequential
    `listdir` calls, and matching keys are yielded as soon as their page arrives.
    """

    def find_files(self, path: str, pattern: str | re.Pattern) -> Iterator[str]:
        regex = re.compile(pattern) if isinstance(pattern, str) else pattern
        prefix = self._normalize_name(clean_name(path))
        if prefix and not prefix.endswith("/"):
            prefix += "/"

        paginator = self.connection.meta.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            for entry in page.get("Contents", ()):
                key = entry["Key"]
                if key.endswith("/"):
                    continue
                relative = key[len(self.location) :].lstrip("/")
                if regex.search(relative):
                    yield relative
