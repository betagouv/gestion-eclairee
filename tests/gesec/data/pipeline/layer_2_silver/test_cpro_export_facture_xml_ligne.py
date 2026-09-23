from gesec.data.pipeline.layer_2_silver.cpro_export_facture_xml_ligne import extract_item_identity


def test_extract_item_identity_numeric_name():
    item = {"cbc:Name": "000000000009000001"}
    description = "Ligne téléphonie\nDétail"

    item_reference, item_name = extract_item_identity(item, description)

    assert item_reference == "000000000009000001"
    assert item_name == "Ligne téléphonie"


def test_extract_item_identity_alphanumeric_name():
    item = {"cbc:Name": "XX9_VOLET_2"}
    description = "Volet 2\nDétail"

    item_reference, item_name = extract_item_identity(item, description)

    assert item_reference is None
    assert item_name == "XX9_VOLET_2"


def test_extract_item_identity_standard_id():
    item = {"cac:StandardItemIdentification": {"cbc:ID": "5650607"}, "cbc:Name": "Article"}
    description = "Libellé\nDétail"

    item_reference, item_name = extract_item_identity(item, description)

    assert item_reference == "5650607"
    assert item_name == "Article"


def test_extract_item_identity_standard_id_without_name():
    item = {"cac:StandardItemIdentification": {"cbc:ID": "5650607"}}
    description = "Libellé\nDétail"

    item_reference, item_name = extract_item_identity(item, description)

    assert item_reference == "5650607"
    assert item_name == "Libellé"


def test_extract_item_identity_missing_name_falls_back_to_description():
    description = "Libellé\nDétail"

    for item in ({}, {"cbc:Name": ""}):
        item_reference, item_name = extract_item_identity(item, description)
        assert item_reference is None
        assert item_name == "Libellé"


def test_extract_item_identity_numeric_name_kept_raw():
    item = {"cbc:Name": " 000000000009000001 "}
    description = "Libellé\nDétail"

    item_reference, item_name = extract_item_identity(item, description)

    assert item_reference == " 000000000009000001 "
    assert item_name == "Libellé"
