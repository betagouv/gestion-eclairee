"""Tests for the export CSV md5 handling and the zip-presence skip in download_cpro."""

import hashlib
from datetime import date

from django.core.files.storage import default_storage

from gesec.data.sync import download_cpro as module

EXPORT_CSV = "Identifiant Chorus Pro;Numéro\n111111111;F1\n222222222;F2\n"


def make_params() -> module.SearchParams:
    return module.SearchParams(
        num_ej="1234567890",
        service="SRV1",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )


class FakeDownload:
    def __init__(self, path):
        self._path = path

    def path(self):
        return self._path

    def delete(self):
        pass


class FakeDownloadInfo:
    def __init__(self, path):
        self._path = path

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def value(self):
        return FakeDownload(self._path)

    def is_done(self):
        return True


class FakePage:
    def __init__(self, path):
        self._path = path
        self.clicked = False
        self.context = FakeContext([self])

    def expect_download(self, timeout):
        return FakeDownloadInfo(self._path)

    def click(self, selector):
        self.clicked = True


class FakeExtraPage:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, pages):
        self._pages = pages

    @property
    def pages(self):
        return [p for p in self._pages if not getattr(p, "closed", False)]


def write_export(tmp_path, content: str = EXPORT_CSV):
    path = tmp_path / "export.csv"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_read_export_ids(tmp_path):
    path = write_export(tmp_path)
    assert module.read_export_ids(path) == {"111111111", "222222222"}


def test_compute_md5(tmp_path):
    path = write_export(tmp_path)
    assert module.compute_md5(path) == hashlib.md5(EXPORT_CSV.encode("utf-8")).hexdigest()


def test_remote_content_md5_missing_returns_none(s3_client):
    assert module.remote_content_md5("cpro/exports/absent.csv") is None


def test_remote_content_md5_matches_etag(s3_client):
    body = EXPORT_CSV.encode("utf-8")
    s3_client.Bucket("test-depec").put_object(Key="cpro/exports/test.csv", Body=body)
    assert module.remote_content_md5("cpro/exports/test.csv") == hashlib.md5(body).hexdigest()


def test_download_export_csv_saves_then_skips_unchanged(s3_client, tmp_path, monkeypatch):
    path = write_export(tmp_path)
    params = make_params()
    expected_key = module.build_export_filename(params)

    monkeypatch.setattr(module, "default_storage", default_storage)
    filepath, ids, changed = module.download_export_csv(FakePage(path), params)

    assert filepath == expected_key
    assert ids == {"111111111", "222222222"}
    assert changed is True
    with default_storage.open(expected_key, "rb") as f:
        assert f.read() == EXPORT_CSV.encode("utf-8")

    _, _, changed_again = module.download_export_csv(FakePage(path), params)
    assert changed_again is False


def test_download_export_csv_closes_extra_pages(s3_client, tmp_path, monkeypatch):
    path = write_export(tmp_path)
    page = FakePage(path)
    extra = FakeExtraPage()
    page.context._pages.append(extra)

    monkeypatch.setattr(module, "default_storage", default_storage)
    module.download_export_csv(page, make_params())

    assert extra.closed
    assert page.context.pages == [page]


def test_search_and_download_skips_loop_when_all_zips_present(s3_client, monkeypatch):
    params = make_params()
    monkeypatch.setattr(module, "init_search_page", lambda page, ignore: None)
    monkeypatch.setattr(module, "fill_service", lambda page, service: None)
    monkeypatch.setattr(module, "fill_num_ej", lambda page, num_ej: None)
    monkeypatch.setattr(module, "fill_date_range", lambda page, start, end: None)
    monkeypatch.setattr(module, "submit_form", lambda page: True)
    monkeypatch.setattr(
        module,
        "download_export_csv",
        lambda page, p: ("cpro/exports/x.csv", {"111111111", "222222222"}, True),
    )

    def fail_download_items(page, p):
        raise AssertionError("download_items should not be called")

    monkeypatch.setattr(module, "download_items", fail_download_items)
    module.search_and_download(None, params, downloaded_ids={"111111111", "222222222"})


def test_search_and_download_runs_loop_when_a_zip_is_missing(s3_client, monkeypatch):
    params = make_params()
    monkeypatch.setattr(module, "init_search_page", lambda page, ignore: None)
    monkeypatch.setattr(module, "fill_service", lambda page, service: None)
    monkeypatch.setattr(module, "fill_num_ej", lambda page, num_ej: None)
    monkeypatch.setattr(module, "fill_date_range", lambda page, start, end: None)
    monkeypatch.setattr(module, "submit_form", lambda page: True)
    monkeypatch.setattr(
        module,
        "download_export_csv",
        lambda page, p: ("cpro/exports/x.csv", {"111111111", "222222222"}, True),
    )
    monkeypatch.setattr(module, "download_items", lambda page, p: {"files": 2, "download": 0, "skip": 1, "error": 0})
    monkeypatch.setattr(module, "go_next_page", lambda page: False)

    module.search_and_download(None, params, downloaded_ids={"111111111"})


def test_accumulate_stats():
    stats = module.new_stats()
    module.accumulate_stats(stats, None)
    module.accumulate_stats(stats, {"skipped": True, "export_csv_updated": 1, "ids": 3})
    module.accumulate_stats(stats, {"export_csv_updated": 0, "files": 5, "download": 2, "skip": 2, "error": 1})

    assert stats == {
        "processed": 3,
        "no_result": 1,
        "skipped": 1,
        "export_csv_updated": 1,
        "files": 5,
        "download": 2,
        "skip": 2,
        "error": 1,
    }


def test_search_and_download_returns_skipped_stats(s3_client, monkeypatch):
    params = make_params()
    monkeypatch.setattr(module, "init_search_page", lambda page, ignore: None)
    monkeypatch.setattr(module, "fill_service", lambda page, service: None)
    monkeypatch.setattr(module, "fill_num_ej", lambda page, num_ej: None)
    monkeypatch.setattr(module, "fill_date_range", lambda page, start, end: None)
    monkeypatch.setattr(module, "submit_form", lambda page: True)
    monkeypatch.setattr(
        module,
        "download_export_csv",
        lambda page, p: ("cpro/exports/x.csv", {"111111111"}, False),
    )

    result = module.search_and_download(None, params, downloaded_ids={"111111111"})
    assert result == {"skipped": True, "export_csv_updated": False, "ids": 1}


def test_load_downloaded_ids(s3_client):
    bucket = s3_client.Bucket("test-depec")
    bucket.put_object(Key="cpro/factures/facture_111111111.zip", Body=b"x")
    bucket.put_object(Key="cpro/factures/facture_222222222_ABC.zip", Body=b"x")
    bucket.put_object(Key="cpro/factures/autre.zip", Body=b"x")

    assert module.load_downloaded_ids() == {"111111111", "222222222"}
