"""Tests for the recursive file search of the custom storages."""

from pathlib import Path

from gesec.storage import FileSystemStorage, find_files


def write_files(root: Path, paths: list[str]) -> None:
    for path in paths:
        filepath = root / path
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text("")


def put_objects(s3_client, keys: list[str], body: bytes = b"x") -> None:
    bucket = s3_client.Bucket("test-depec")
    for key in keys:
        bucket.put_object(Key=key, Body=body)


class TestFileSystemStorageFindFiles:
    def test_find_files_matches_recursive_regex(self, tmp_path):
        write_files(
            tmp_path,
            [
                "cpro/factures/facture_111111111.zip",
                "cpro/factures_unzipped/facture_111111111/pivot/FAC.xml",
                "cpro/factures_unzipped/facture_111111111/pivot/PJ.pdf.factur-x.xml",
                "cpro/factures_unzipped/facture_111111111/pivot/PJ.pdf",
                "cpro/factures_unzipped/facture_111111111/PivotS.xml",
            ],
        )
        storage = FileSystemStorage(location=str(tmp_path))

        assert sorted(storage.find_files("cpro/factures_unzipped", r"/pivot/.*\.xml$")) == [
            "cpro/factures_unzipped/facture_111111111/pivot/FAC.xml",
            "cpro/factures_unzipped/facture_111111111/pivot/PJ.pdf.factur-x.xml",
        ]

    def test_find_files_excludes_directories(self, tmp_path):
        write_files(tmp_path, ["cpro/facture_111111111/pivot/facture.xml"])
        storage = FileSystemStorage(location=str(tmp_path))

        assert sorted(storage.find_files("cpro", r"facture")) == ["cpro/facture_111111111/pivot/facture.xml"]

    def test_find_files_missing_path_yields_nothing(self, tmp_path):
        storage = FileSystemStorage(location=str(tmp_path))

        assert list(storage.find_files("missing", r".*")) == []


class TestS3StorageFindFiles:
    def test_find_files_matches_recursive_regex(self, s3_client):
        put_objects(
            s3_client,
            [
                "find-test/cpro/facture_111111111.zip",
                "find-test/cpro/factures_unzipped/facture_111111111/pivot/FAC.xml",
                "find-test/cpro/factures_unzipped/facture_111111111/pivot/PJ.pdf.factur-x.xml",
                "find-test/cpro/factures_unzipped/facture_111111111/pivot/PJ.pdf",
                "find-test/cpro/factures_unzipped/facture_111111111/PivotS.xml",
            ],
        )

        assert sorted(find_files("find-test/cpro/factures_unzipped", r"/pivot/.*\.xml$")) == [
            "find-test/cpro/factures_unzipped/facture_111111111/pivot/FAC.xml",
            "find-test/cpro/factures_unzipped/facture_111111111/pivot/PJ.pdf.factur-x.xml",
        ]

    def test_find_files_matches_zip_regex(self, s3_client):
        put_objects(
            s3_client,
            [
                "find-zip-test/facture_111111111.zip",
                "find-zip-test/facture_222222222.zip",
                "find-zip-test/facture_abc.zip",
            ],
        )

        assert sorted(find_files("find-zip-test", r"facture_\d+\.zip$")) == [
            "find-zip-test/facture_111111111.zip",
            "find-zip-test/facture_222222222.zip",
        ]

    def test_find_files_ignores_folder_markers(self, s3_client):
        put_objects(s3_client, ["find-markers-test/cpro/", "find-markers-test/cpro/facture.xml"])

        assert list(find_files("find-markers-test", r".*")) == ["find-markers-test/cpro/facture.xml"]

    def test_find_files_missing_prefix_yields_nothing(self, s3_client):
        assert list(find_files("find-missing-test", r".*")) == []
