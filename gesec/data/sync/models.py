from django.db import models


class SftpIngestState(models.Model):
    """État de suivi de l'ingestion nocturne du bucket SFTP (base applicative)."""

    path = models.CharField(max_length=1024, primary_key=True)
    etag = models.CharField(max_length=64)
    last_modified = models.DateTimeField()
    tables = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.path
