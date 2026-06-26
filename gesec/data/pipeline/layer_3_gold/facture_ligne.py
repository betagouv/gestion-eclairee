import json
from decimal import Decimal

from sqlalchemy import text

from gesec.data.pipeline.db import create_engine, save_list_pydantic
from gesec.data.pipeline.layer_1_bronze.cpro_export_facture_xml import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproExportFactureXml
from gesec.data.pipeline.layer_3_gold.schemas import GoldCproExportFactureLigne

TABLE_NAME = "gesec_facture_ligne"


def load_bronze_rows(table_name: str) -> list[BronzeCproExportFactureXml]:
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM {table_name}"))
        rows = result.fetchall()
        return [BronzeCproExportFactureXml(**row._asdict()) for row in rows]


def transform_xml_to_gold(content: dict, id_cpro: str, xml_schema: str) -> list[GoldCproExportFactureLigne]:
    result = []
    for line in content["cac:InvoiceLine"]:
        item = line["cac:Item"]
        std_id = item.get("cac:StandardItemIdentification")
        line_amount_excl_tax = Decimal(line["cbc:LineExtensionAmount"]["$"])
        if line_amount_excl_tax.is_zero():
            line_amount_tax = Decimal("0")
        else:
            if "cac:TaxTotal" in item:
                line_amount_tax = item["cac:TaxTotal"]["cbc:TaxAmount"]["$"]
            elif "cac:ClassifiedTaxCategory" in item:
                tax_categories = item["cac:ClassifiedTaxCategory"]
                assert len(tax_categories) == 1, f"Many tax categories: {tax_categories}"
                tax_category = tax_categories[0]
                assert tax_category["cac:TaxScheme"]["cbc:TaxTypeCode"] == "TVA"
                tax_percent = Decimal(tax_category["cbc:Percent"])
                line_amount_tax = line_amount_excl_tax * tax_percent / Decimal("100")
            else:
                raise ValueError(f"Cannot extract taxes from {id_cpro}")
        line_amount_incl_tax = line_amount_excl_tax + line_amount_tax
        unit_price_currency = line["cac:Price"]["cbc:PriceAmount"]["@currencyID"]
        line_price_currency = line["cbc:LineExtensionAmount"]["@currencyID"]
        assert unit_price_currency == line_price_currency, (
            f"Currency missmatch: {unit_price_currency} != {line_price_currency}"
        )
        currency = line_price_currency
        result.append(
            GoldCproExportFactureLigne(
                id_cpro=id_cpro,
                xml_schema=xml_schema,
                line_id=line["cbc:ID"],
                quantity_unit_code=line["cbc:InvoicedQuantity"]["@unitCode"],
                quantity=line["cbc:InvoicedQuantity"]["$"],
                item_name=line["cac:Item"]["cbc:Name"],
                item_description="\n".join(line["cac:Item"]["cbc:Description"]),
                item_reference=std_id["cbc:ID"] if std_id is not None else None,
                unit_price=line["cac:Price"]["cbc:PriceAmount"]["$"],
                line_amount_excl_tax=line_amount_excl_tax,
                line_amount_incl_tax=line_amount_incl_tax,
                line_amount_vat=line_amount_tax,
                currency=currency,
            )
        )
    # Ajout des lignes des charges (ex: livraison)
    for charge_idx, charge in enumerate(content.get("cac:AllowanceCharge", [])):
        amount = Decimal(charge["cbc:Amount"]["$"])
        # Fixe la TVA à 20%
        line_amount_tax = Decimal("0.2") * amount
        line_amount_excl_tax = amount
        line_amount_incl_tax = line_amount_excl_tax + line_amount_tax
        result.append(
            GoldCproExportFactureLigne(
                id_cpro=id_cpro,
                xml_schema=xml_schema,
                line_id=f"charge_{charge_idx}",
                quantity_unit_code="",
                quantity=Decimal("1"),
                item_name=charge["cbc:AllowanceChargeReason"],
                item_description=json.dumps(charge),
                item_reference=charge["cbc:AllowanceChargeReason"],
                unit_price=amount,
                line_amount_excl_tax=line_amount_excl_tax,
                line_amount_incl_tax=line_amount_incl_tax,
                line_amount_vat=line_amount_tax,
                currency=charge["cbc:Amount"]["@currencyID"],
            )
        )
    return result


def transform_to_gold(
    bronze_factures_xml: list[BronzeCproExportFactureXml],
) -> list[GoldCproExportFactureLigne]:
    result = []
    for fac in bronze_factures_xml:
        lines = transform_xml_to_gold(fac.content, fac.id_cpro, fac.xml_schema)
        result.extend(lines)
    return result


def process_to_gold(
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
) -> None:
    bronze_factures = load_bronze_rows(bronze_table_name)
    gold_lines = transform_to_gold(bronze_factures)
    save_list_pydantic(gold_lines, TABLE_NAME, if_exists="replace")
