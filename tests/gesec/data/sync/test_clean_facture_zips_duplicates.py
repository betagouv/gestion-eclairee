"""Tests for the S3 facture zip duplicate cleaner."""

import pytest

from gesec.data.sync.clean_facture_zips_duplicates import (
    clean_duplicates,
    find_folder_duplicates,
    find_zip_duplicates,
)


def put_objects(s3_client, keys: list[str]) -> None:
    bucket = s3_client.Bucket("test-depec")
    for key in keys:
        bucket.put_object(Key=key, Body=b"x")


def list_keys(s3_client, prefix: str) -> set[str]:
    bucket = s3_client.Bucket("test-depec")
    return {obj.key for obj in bucket.objects.filter(Prefix=prefix)}


class TestFindZipDuplicates:
    def test_detects_suffixed_variant_of_canonical_archive(self, s3_client):
        prefix = "zip-detect/cpro/factures"
        put_objects(
            s3_client,
            [
                f"{prefix}/facture_111111111.zip",
                f"{prefix}/facture_111111111_a1B2c3D.zip",
            ],
        )

        assert find_zip_duplicates(prefix) == [
            (f"{prefix}/facture_111111111_a1B2c3D.zip", f"{prefix}/facture_111111111.zip")
        ]

    def test_keeps_orphan_variant_without_canonical_archive(self, s3_client):
        prefix = "zip-orphan/cpro/factures"
        put_objects(s3_client, [f"{prefix}/facture_222222222_a1B2c3D.zip"])

        assert find_zip_duplicates(prefix) == []

    def test_ignores_canonical_archives(self, s3_client):
        prefix = "zip-canonical/cpro/factures"
        put_objects(
            s3_client,
            [
                f"{prefix}/facture_111111111.zip",
                f"{prefix}/facture_222222222.zip",
            ],
        )

        assert find_zip_duplicates(prefix) == []

    def test_matches_id_prefix_when_variant_has_numeric_slug(self, s3_client):
        prefix = "zip-numeric/cpro/factures"
        put_objects(
            s3_client,
            [
                f"{prefix}/facture_333333333.zip",
                f"{prefix}/facture_333333333_1234567.zip",
            ],
        )

        assert find_zip_duplicates(prefix) == [
            (f"{prefix}/facture_333333333_1234567.zip", f"{prefix}/facture_333333333.zip")
        ]


class TestFindFolderDuplicates:
    def test_detects_folder_inherited_from_doublon_zip(self, s3_client):
        prefix = "folder-detect/cpro/factures_unzipped"
        put_objects(
            s3_client,
            [
                f"{prefix}/facture_111111111/PivotS.xml",
                f"{prefix}/facture_111111111_a1B2c3D/PivotS.xml",
            ],
        )

        assert find_folder_duplicates(prefix) == [
            (f"{prefix}/facture_111111111_a1B2c3D", f"{prefix}/facture_111111111")
        ]

    def test_keeps_orphan_folder_without_canonical_folder(self, s3_client):
        prefix = "folder-orphan/cpro/factures_unzipped"
        put_objects(s3_client, [f"{prefix}/facture_222222222_a1B2c3D/PivotS.xml"])

        assert find_folder_duplicates(prefix) == []

    def test_ignores_canonical_folders(self, s3_client):
        prefix = "folder-canonical/cpro/factures_unzipped"
        put_objects(
            s3_client,
            [
                f"{prefix}/facture_111111111/PivotS.xml",
                f"{prefix}/facture_222222222/PivotS.xml",
            ],
        )

        assert find_folder_duplicates(prefix) == []


class TestCleanDuplicates:
    def test_dry_run_deletes_nothing(self, s3_client):
        prefix = "clean-dryrun/cpro"
        put_objects(
            s3_client,
            [
                f"{prefix}/factures/facture_111111111.zip",
                f"{prefix}/factures/facture_111111111_a1B2c3D.zip",
            ],
        )

        stats = clean_duplicates(prefix, apply=False)

        assert stats == {"zip_duplicates": 1, "folder_duplicates": 0, "removed": 0}
        assert f"{prefix}/factures/facture_111111111_a1B2c3D.zip" in list_keys(s3_client, prefix)

    def test_apply_deletes_zip_duplicate_and_keeps_canonical(self, s3_client):
        prefix = "clean-apply/cpro"
        put_objects(
            s3_client,
            [
                f"{prefix}/factures/facture_111111111.zip",
                f"{prefix}/factures/facture_111111111_a1B2c3D.zip",
                f"{prefix}/factures/facture_222222222.zip",
            ],
        )

        stats = clean_duplicates(prefix, apply=True)

        assert stats == {"zip_duplicates": 1, "folder_duplicates": 0, "removed": 1}
        assert list_keys(s3_client, prefix) == {
            f"{prefix}/factures/facture_111111111.zip",
            f"{prefix}/factures/facture_222222222.zip",
        }

    def test_apply_deletes_folder_duplicate_recursively(self, s3_client):
        prefix = "clean-folder/cpro"
        put_objects(
            s3_client,
            [
                f"{prefix}/factures_unzipped/facture_111111111/PivotS.xml",
                f"{prefix}/factures_unzipped/facture_111111111/pivot/FAC.xml",
                f"{prefix}/factures_unzipped/facture_111111111_a1B2c3D/PivotS.xml",
                f"{prefix}/factures_unzipped/facture_111111111_a1B2c3D/pivot/FAC.xml",
            ],
        )

        stats = clean_duplicates(prefix, apply=True)

        assert stats == {"zip_duplicates": 0, "folder_duplicates": 1, "removed": 1}
        assert list_keys(s3_client, prefix) == {
            f"{prefix}/factures_unzipped/facture_111111111/PivotS.xml",
            f"{prefix}/factures_unzipped/facture_111111111/pivot/FAC.xml",
        }

    def test_refuses_apply_on_non_s3_storage(self, monkeypatch):
        from django.core.files.storage import FileSystemStorage

        monkeypatch.setattr("gesec.data.sync.clean_facture_zips_duplicates.default_storage", FileSystemStorage())

        with pytest.raises(RuntimeError, match="STORAGE_BACKEND=s3"):
            clean_duplicates("cpro", apply=True)
