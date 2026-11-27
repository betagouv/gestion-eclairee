"""Tests for the export CSV md5 handling and the zip-presence skip in download_cpro."""

import hashlib
import zipfile
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


class FakeKeyboard:
    def press(self, key):
        pass

    def type(self, text):
        pass


class FakeItemButton:
    def __init__(self, page, id_chorus):
        self.page = page
        self.id_chorus = id_chorus

    def get_attribute(self, name):
        return self.id_chorus if name == "data-value" else None

    def click(self):
        self.page.clicks.append("Synthese_Btn_TelechargerUnitaire")


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def get_attribute(self, name):
        if name == "aria-expanded":
            return "true"
        if name == "disabled":
            return "disabled"
        return None

    def click(self):
        self.page.clicks.append(self.selector)

    def scroll_into_view_if_needed(self):
        pass

    def count(self):
        return len(self.page.site.download_ids)

    def nth(self, i):
        return FakeItemButton(self.page, self.page.site.download_ids[i])


class FakeSite:
    """Simule le site CPRO : file des téléchargements et ids des factures trouvées."""

    def __init__(self, downloads, download_ids):
        self.downloads = list(downloads)
        self.download_ids = download_ids
        self.visited_urls = []

    def next_download(self):
        return self.downloads.pop(0)


class FakeBrowserPage:
    def __init__(self, context, site):
        self.context = context
        self.site = site
        self.closed = False
        self.clicks = []
        self.fills = []
        self.keyboard = FakeKeyboard()

    def goto(self, url, wait_until=None, timeout=None):
        self.site.visited_urls.append(url)

    def select_option(self, selector, value=None):
        pass

    def locator(self, selector):
        return FakeLocator(self, selector)

    def click(self, selector):
        self.clicks.append(selector)

    def fill(self, selector, value):
        self.fills.append((selector, value))

    def query_selector(self, selector):
        if "Résultats de la recherche" in selector:
            return object()
        return None

    def wait_for_load_state(self, state=None):
        pass

    def expect_download(self, timeout):
        return FakeDownloadInfo(self.site.next_download())

    def close(self):
        self.closed = True
        if self in self.context.pages:
            self.context.pages.remove(self)


class FakeBrowserContext:
    def __init__(self, site):
        self.site = site
        self.pages = []
        self.cookies = []
        self.close_count = 0

    def add_cookies(self, cookies):
        self.cookies.extend(cookies)

    def new_page(self):
        page = FakeBrowserPage(self, self.site)
        self.pages.append(page)
        return page

    def close(self):
        self.close_count += 1


def make_facture_zip(path, id_cpro):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("PivotS.xml", f"<PivotS><IdCPRO>{id_cpro}</IdCPRO></PivotS>")
    return str(path)


def test_main_golden_path(s3_client, tmp_path, monkeypatch):
    monkeypatch.setenv("JSESSIONID", "fake-jsessionid")
    monkeypatch.setattr(module, "default_storage", default_storage)

    input_csv = tmp_path / "input.csv"
    input_csv.write_text("EJ,SERVICES,FACTURE_NUM,FACTURE_MONTANT\n1512933394,FAC9420075,,\n", encoding="utf-8")
    export_csv = tmp_path / "export.csv"
    export_csv.write_text("Identifiant Chorus Pro;Numéro\n333333333;F1\n444444444;F2\n", encoding="utf-8")
    zip_1 = make_facture_zip(tmp_path / "facture_1.zip", "333333333")
    zip_2 = make_facture_zip(tmp_path / "facture_2.zip", "444444444")

    site = FakeSite(downloads=[str(export_csv), zip_1, zip_2], download_ids=["333333333", "444444444"])
    contexts = []

    def fake_launch_context(headless=True, locale=None):
        ctx = FakeBrowserContext(site)
        contexts.append(ctx)
        return ctx

    monkeypatch.setattr(module, "launch_context", fake_launch_context)

    module.main(["--input-file", str(input_csv), "--start", "2026-01-01", "--end", "2026-12-31"])

    assert len(contexts) == 1
    assert contexts[0].close_count == 1
    assert contexts[0].cookies == [
        {"name": "JSESSIONID", "value": "fake-jsessionid", "domain": "cpro.chorus-pro.gouv.fr", "path": "/cpp"}
    ]
    assert site.visited_urls == ["https://cpro.chorus-pro.gouv.fr/cpp/rechercheFactures"]
    page = contexts[0].pages[0]
    assert ("input[name='listeServices.critere.code']", "FAC9420075") in page.fills
    assert ("input[name='listeResultats.critere.numeroBonDeCommande']", "1512933394") in page.fills
    assert "#GFR_RechercheFactureEtatAcompteRecus_Criteres_BoutonRechercher" in page.clicks
    export_key = "cpro/exports/1512933394_FAC9420075_20260101_20261231.csv"
    with default_storage.open(export_key, "rb") as f:
        assert f.read() == export_csv.read_bytes()

    for id_cpro in ("333333333", "444444444"):
        with default_storage.open(f"cpro/factures/facture_{id_cpro}.zip", "rb") as f:
            with zipfile.ZipFile(f) as z:
                assert f"<IdCPRO>{id_cpro}</IdCPRO>" in z.read("PivotS.xml").decode("utf-8")
