import json
from decimal import Decimal

from tqdm import tqdm

from gesec.data.pipeline.db import load_rows_from_table, save_list_pydantic
from gesec.data.pipeline.layer_1_bronze.cpro_export_facture_xml import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproExportFactureXml
from gesec.data.pipeline.utils import force_string, rget

from .schemas import SilverCproExportFactureXmlLigne

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]


def load_bronze_rows(table_name: str) -> list[BronzeCproExportFactureXml]:
    return load_rows_from_table(table_name, BronzeCproExportFactureXml)


def transform_xml_to_silver(content: dict, id_cpro: str, xml_schema: str) -> list[SilverCproExportFactureXmlLigne]:
    result = []
    for line in content["cac:InvoiceLine"]:
        item = line["cac:Item"]
        std_id = item.get("cac:StandardItemIdentification")
        line_amount_excl_tax = Decimal(line["cbc:LineExtensionAmount"]["$"])
        line_amount_tax = None
        if line_amount_excl_tax.is_zero():
            line_amount_tax = Decimal("0")
        else:
            if "cac:TaxTotal" in item:
                line_amount_tax = item["cac:TaxTotal"]["cbc:TaxAmount"]["$"]
            elif "cac:ClassifiedTaxCategory" in item:
                tax_categories = item["cac:ClassifiedTaxCategory"]
                assert len(tax_categories) == 1, f"Many tax categories: {tax_categories}"
                tax_category = tax_categories[0]
                tax_type_code = rget(tax_category, "cac:TaxScheme.cbc:TaxTypeCode")
                assert (
                    # 2.0 // UGAP (TVA) Bechtle direct (TVA DEBIT) INETUM (VAT)
                    ("TVA" in str(tax_type_code) or "VAT" in str(tax_type_code))
                    # 2.1 // SCC
                    or rget(tax_category, "cac:TaxScheme.cbc:ID") == "VAT"
                    or rget(tax_category, "cac:TaxScheme.cbc:ID.$") == "VAT"
                    # Or empty tax scheme
                    or rget(tax_category, "cac:TaxScheme") is None
                ), f"Weird tax {id_cpro} {tax_category}"
                if "cbc:Percent" in tax_category:
                    tax_percent = tax_category["cbc:Percent"]
                    if isinstance(tax_percent, str):
                        tax_percent = Decimal(tax_percent)
                    elif isinstance(tax_percent, dict):
                        tax_percent = Decimal(tax_percent["$"])
                    else:
                        raise ValueError(f"Invalid tax percent format {tax_category!r}")
                    line_amount_tax = line_amount_excl_tax * tax_percent / Decimal("100")

        # Essaie d'extraire la tva depuis le montant total de la facture
        # Ne marche que s'il y a une seule TVA
        if line_amount_tax is None:
            tax_total = content["cac:TaxTotal"]
            if len(tax_total) == 1:
                tax_subtotal = tax_total[0]["cac:TaxSubtotal"]
                if len(tax_subtotal) == 1:
                    tax_percent = Decimal(tax_subtotal[0]["cbc:Percent"])
                    line_amount_tax = line_amount_excl_tax * tax_percent / Decimal("100")

        if line_amount_tax is None:
            raise ValueError(f"Cannot extract taxes from {id_cpro} {item!r}")

        line_amount_incl_tax = line_amount_excl_tax + line_amount_tax
        unit_price_currency = line["cac:Price"]["cbc:PriceAmount"]["@currencyID"]
        line_price_currency = line["cbc:LineExtensionAmount"]["@currencyID"]
        if line_price_currency:
            assert not unit_price_currency or line_price_currency == unit_price_currency, (
                f"Currency missmatch: {unit_price_currency!r} != {line_price_currency!r}"
            )
            currency = line_price_currency
        elif unit_price_currency:
            assert not line_price_currency or line_price_currency == unit_price_currency, (
                f"Currency missmatch: {unit_price_currency!r} != {line_price_currency!r}"
            )
            currency = unit_price_currency
        else:
            raise ValueError(f"Cannot extract currency {id_cpro} {line!r}")

        quantity_obj = line["cbc:InvoicedQuantity"]
        if isinstance(quantity_obj, dict):
            quantity_unit_code = quantity_obj["@unitCode"]
            quantity = quantity_obj["$"]
        elif isinstance(quantity_obj, (str, int, float, Decimal)):
            quantity_unit_code = ""
            quantity = Decimal(quantity_obj)
        else:
            raise ValueError(f"Unknown quantity type {quantity_obj!r}")

        item_description = "\n".join(x for x in line["cac:Item"].get("cbc:Description", [""]) if x)
        line_note = line.get("cbc:Note", "")

        try:
            result.append(
                SilverCproExportFactureXmlLigne(
                    id_cpro=id_cpro,
                    xml_schema=xml_schema,
                    line_id=line["cbc:ID"],
                    quantity_unit_code=quantity_unit_code,
                    quantity=quantity,
                    item_name=line["cac:Item"].get("cbc:Name") or item_description.split("\n")[0],
                    item_description=item_description + (f"\n{line_note}" if line_note else ""),
                    item_reference=std_id["cbc:ID"] if std_id is not None else None,
                    unit_price=line["cac:Price"]["cbc:PriceAmount"]["$"],
                    line_amount_excl_tax=line_amount_excl_tax,
                    line_amount_incl_tax=line_amount_incl_tax,
                    line_amount_vat=line_amount_tax,
                    currency=currency,
                )
            )
        except Exception:
            print("Weird line", id_cpro, repr(line))
            raise
    # Ajout des lignes des charges (ex: livraison)
    for charge_idx, charge in enumerate(content.get("cac:AllowanceCharge", [])):
        amount = Decimal(charge["cbc:Amount"]["$"])
        # Fixe la TVA à 20%
        line_amount_tax = Decimal("0.2") * amount
        line_amount_excl_tax = amount
        line_amount_incl_tax = line_amount_excl_tax + line_amount_tax
        allowance_charge_reason = None
        if "cbc:AllowanceChargeReason" in charge:
            allowance_charge_reason = force_string(charge["cbc:AllowanceChargeReason"])
        if not allowance_charge_reason:
            allowance_charge_reason = charge["cbc:AllowanceChargeReasonCode"]
        result.append(
            SilverCproExportFactureXmlLigne(
                id_cpro=id_cpro,
                xml_schema=xml_schema,
                line_id=f"charge_{charge_idx}",
                quantity_unit_code="",
                quantity=Decimal("1"),
                item_name=allowance_charge_reason,
                item_description=json.dumps(charge),
                item_reference=allowance_charge_reason,
                unit_price=amount,
                line_amount_excl_tax=line_amount_excl_tax,
                line_amount_incl_tax=line_amount_incl_tax,
                line_amount_vat=line_amount_tax,
                currency=charge["cbc:Amount"]["@currencyID"],
            )
        )
    return result


def transform_to_silver(
    bronze_factures_xml: list[BronzeCproExportFactureXml],
) -> list[SilverCproExportFactureXmlLigne]:
    result = []
    for fac in tqdm(bronze_factures_xml):
        lines = transform_xml_to_silver(fac.content, fac.id_cpro, fac.xml_schema)
        result.extend(lines)
    return result


def process_to_silver(
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
    silver_table_name: str = DEFAULT_TABLE_NAME,
) -> None:
    bronze_factures = load_bronze_rows(bronze_table_name)
    silver_lines = transform_to_silver(bronze_factures)
    save_list_pydantic(silver_lines, silver_table_name, if_exists="replace")
