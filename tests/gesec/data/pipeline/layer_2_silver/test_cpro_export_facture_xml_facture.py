import logging

from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproExportFactureXml
from gesec.data.pipeline.layer_2_silver.cpro_export_facture_xml_facture import (
    extract_delivery_id,
    extract_reference_ugap,
    transform_to_silver,
)


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


def test_extract_delivery_id_absent():
    assert extract_delivery_id({}) is None


def test_extract_delivery_id_empty_is_ignored():
    assert extract_delivery_id({"cac:Delivery": {"cbc:ID": ""}}) is None
    content = {
        "cac:Delivery": [
            {"cbc:ID": ""},
            {"cbc:ID": "0900000001-0080000002"},
        ]
    }

    assert extract_delivery_id(content) == "0900000001-0080000002"


def test_extract_delivery_id_multiple_distinct_keeps_first_and_warns(caplog):
    content = {
        "cac:Delivery": [
            {"cbc:ID": "0900000001-0080000002"},
            {"cbc:ID": "0900000003-0080000004"},
        ]
    }

    with caplog.at_level(logging.WARNING):
        delivery_id = extract_delivery_id(content)

    assert delivery_id == "0900000001-0080000002"
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert "0900000003-0080000004" in caplog.text


def test_extract_reference_ugap_list():
    content = {"cbc:Note": ["Texte libre", "Référence UGAP : 0900000005", "Autre"]}

    assert extract_reference_ugap(content) == "900000005"


def test_extract_reference_ugap_string():
    assert extract_reference_ugap({"cbc:Note": "Référence UGAP : 0900000005"}) == "900000005"


def test_extract_reference_ugap_dict():
    assert extract_reference_ugap({"cbc:Note": {"$": "Référence UGAP : 0900000005"}}) == "900000005"


def test_extract_reference_ugap_absent():
    assert extract_reference_ugap({}) is None


def test_extract_reference_ugap_without_label():
    assert extract_reference_ugap({"cbc:Note": ["Texte libre", "Sans libellé"]}) is None
    assert extract_reference_ugap({"cbc:Note": "Référence UGAP : ABC"}) is None


def test_extract_reference_ugap_strips_leading_zeros():
    assert extract_reference_ugap({"cbc:Note": "Référence UGAP : 0900000001"}) == "900000001"
    assert extract_reference_ugap({"cbc:Note": "Référence UGAP : 000"}) == "0"


def test_transform_to_silver_fills_delivery_id_and_reference_ugap():
    content = {
        "cbc:ID": "7001234567",
        "cac:Delivery": {"cbc:ID": "0900000001-0080000002"},
        "cbc:Note": ["Facture", "Référence UGAP : 0900000001"],
    }

    factures = transform_to_silver([bronze_facture(content)])

    assert len(factures) == 1
    assert factures[0].numero == "7001234567"
    assert factures[0].delivery_id == "0900000001-0080000002"
    assert factures[0].reference_ugap == "900000001"


def test_transform_to_silver_keeps_facture_without_note():
    content = {
        "cbc:ID": "7001234567",
        "cac:Delivery": {"cbc:ID": "0900000001-0080000002"},
    }

    factures = transform_to_silver([bronze_facture(content)])

    assert len(factures) == 1
    assert factures[0].reference_ugap is None


def test_transform_to_silver_skips_facture_without_numero():
    content = {"cac:Delivery": {"cbc:ID": "0900000001-0080000002"}}

    assert transform_to_silver([bronze_facture(content)]) == []
