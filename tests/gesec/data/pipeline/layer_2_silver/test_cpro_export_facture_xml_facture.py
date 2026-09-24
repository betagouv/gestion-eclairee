import logging

from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproExportFactureXml
from gesec.data.pipeline.layer_2_silver import cpro_export_facture_xml_facture as module
from gesec.data.pipeline.layer_2_silver.cpro_export_facture_xml_facture import (
    extract_delivery_id,
    extract_note,
    transform_to_silver,
)
from gesec.data.pipeline.layer_2_silver.schemas import SilverCproExportFactureXmlFactureStatus


def bronze_facture(content: dict, id_cpro: str = "1") -> BronzeCproExportFactureXml:
    return BronzeCproExportFactureXml(id_cpro=id_cpro, xml_schema="UBL-Invoice-2", content=content)


def test_extract_delivery_id_string():
    content = {"cac:Delivery": {"cbc:ID": "0900000001-0080000002"}}

    assert extract_delivery_id(content) == "0900000001-0080000002"


def test_extract_delivery_id_dict():
    content = {"cac:Delivery": {"cbc:ID": {"$": "0900000001-0080000002"}}}

    assert extract_delivery_id(content) == "0900000001-0080000002"


def test_extract_delivery_id_list_keeps_first():
    content = {
        "cac:Delivery": [
            {"cbc:ID": "0900000001-0080000002"},
            {"cbc:ID": "0900000003-0080000004"},
        ]
    }

    assert extract_delivery_id(content) == "0900000001-0080000002"


def test_extract_delivery_id_skips_null_item():
    content = {"cac:Delivery": [None, {"cbc:ID": "0900000001-0080000002"}]}

    assert extract_delivery_id(content) == "0900000001-0080000002"


def test_extract_delivery_id_empty_values_are_ignored():
    assert extract_delivery_id({"cac:Delivery": {"cbc:ID": ""}}) is None
    assert extract_delivery_id({"cac:Delivery": {"cbc:ID": None}}) is None
    assert extract_delivery_id({"cac:Delivery": [{"cbc:ID": " "}]}) is None

    content = {"cac:Delivery": [{"cbc:ID": ""}, {"cbc:ID": "0900000001-0080000002"}]}

    assert extract_delivery_id(content) == "0900000001-0080000002"


def test_extract_delivery_id_absent_or_null_is_none():
    assert extract_delivery_id({}) is None
    assert extract_delivery_id({"cac:Delivery": None}) is None
    assert extract_delivery_id({"cac:Delivery": []}) is None
    assert extract_delivery_id({"cac:Delivery": [None]}) is None
    assert extract_delivery_id({"cac:Delivery": [{}]}) is None


def test_extract_delivery_id_unknown_shapes_are_none():
    assert extract_delivery_id({"cac:Delivery": "0900000001-0080000002"}) is None
    assert extract_delivery_id({"cac:Delivery": [42]}) is None
    assert extract_delivery_id({"cac:Delivery": [{"cbc:ID": ["0900000001"]}]}) is None
    assert extract_delivery_id({"cac:Delivery": [{"cbc:ID": 42}]}) is None


def test_extract_note_joins_strings():
    content = {"cbc:Note": ["Facture", "Référence UGAP : 0900000001"]}

    assert extract_note(content) == "Facture\nRéférence UGAP : 0900000001"


def test_extract_note_dict_value():
    assert extract_note({"cbc:Note": {"$": "Texte"}}) == "Texte"


def test_extract_note_single_string():
    assert extract_note({"cbc:Note": "Texte"}) == "Texte"


def test_extract_note_ignores_null_and_empty():
    assert extract_note({"cbc:Note": [None]}) == ""
    assert extract_note({"cbc:Note": ["", "Texte"]}) == "Texte"
    assert extract_note({"cbc:Note": [None, "Un", {"$": "Deux"}]}) == "Un\nDeux"


def test_extract_note_ignores_exotic_types():
    assert extract_note({"cbc:Note": [42, ["Texte"]]}) == ""
    assert extract_note({"cbc:Note": 42}) == ""
    assert extract_note({"cbc:Note": {"$": None}}) == ""


def test_extract_note_absent():
    assert extract_note({}) == ""
    assert extract_note({"cbc:Note": None}) == ""


def test_transform_to_silver_fills_delivery_note_and_status():
    content = {
        "cbc:ID": "7001234567",
        "cac:Delivery": {"cbc:ID": "0900000001-0080000002"},
        "cbc:Note": ["Facture", "Référence UGAP : 0900000001"],
    }

    factures, statuses = transform_to_silver([bronze_facture(content)])

    assert len(factures) == 1
    assert factures[0].numero == "7001234567"
    assert factures[0].delivery == {"cbc:ID": "0900000001-0080000002"}
    assert factures[0].delivery_id == "0900000001-0080000002"
    assert factures[0].note == "Facture\nRéférence UGAP : 0900000001"
    assert statuses == [SilverCproExportFactureXmlFactureStatus(id_cpro="1", status="Ok")]


def test_transform_to_silver_keeps_facture_with_empty_delivery_and_note():
    content = {"cbc:ID": "7001234567", "cac:Delivery": [None], "cbc:Note": [None]}

    factures, statuses = transform_to_silver([bronze_facture(content)])

    assert len(factures) == 1
    assert factures[0].delivery == [None]
    assert factures[0].delivery_id is None
    assert factures[0].note == ""
    assert statuses == [SilverCproExportFactureXmlFactureStatus(id_cpro="1", status="Ok")]


def test_transform_to_silver_exposes_all_delivery_ids_in_raw_delivery():
    delivery = [{"cbc:ID": "0900000001-0080000002"}, {"cbc:ID": "0900000003-0080000004"}]
    content = {"cbc:ID": "7001234567", "cac:Delivery": delivery}

    factures, statuses = transform_to_silver([bronze_facture(content)])

    assert factures[0].delivery_id == "0900000001-0080000002"
    assert factures[0].delivery == delivery
    assert statuses == [SilverCproExportFactureXmlFactureStatus(id_cpro="1", status="Ok")]


def test_transform_to_silver_flags_facture_without_numero():
    content = {"cac:Delivery": {"cbc:ID": "0900000001-0080000002"}}

    factures, statuses = transform_to_silver([bronze_facture(content)])

    assert factures == []
    assert len(statuses) == 1
    assert statuses[0].status == "Error"
    assert statuses[0].status_details


def test_transform_to_silver_isolates_facture_error(monkeypatch, caplog):
    def boom(content):
        if content.get("cbc:ID") == "7001234567":
            raise ValueError("boom")
        return None

    broken = bronze_facture({"cbc:ID": "7001234567"}, id_cpro="broken")
    healthy = bronze_facture({"cbc:ID": "7001234568"}, id_cpro="healthy")
    monkeypatch.setattr(module, "extract_delivery_id", boom)

    with caplog.at_level(logging.ERROR):
        factures, statuses = transform_to_silver([broken, healthy])

    assert [facture.id_cpro for facture in factures] == ["healthy"]
    assert statuses == [
        SilverCproExportFactureXmlFactureStatus(id_cpro="broken", status="Error", status_details="ValueError('boom')"),
        SilverCproExportFactureXmlFactureStatus(id_cpro="healthy", status="Ok"),
    ]
    assert any(record.levelno == logging.ERROR for record in caplog.records)
