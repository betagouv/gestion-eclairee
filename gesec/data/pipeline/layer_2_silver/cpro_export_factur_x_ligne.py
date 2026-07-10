import json
from decimal import Decimal

from tqdm import tqdm

from gesec.data.pipeline.db import save_list_pydantic, load_rows_from_table
from gesec.data.pipeline.layer_1_bronze.cpro_export_factur_x import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproExportFacturX
from gesec.data.pipeline.layer_2_silver.schemas import SilverCproExportFacturXLigne
from gesec.data.pipeline.utils import rget

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]


def load_bronze_rows(table_name: str) -> list[BronzeCproExportFacturX]:
    return load_rows_from_table(table_name, BronzeCproExportFacturX)


def transform_xml_to_silver(content: dict, id_cpro: str, xml_schema: str) -> list[SilverCproExportFacturXLigne]:
    result = []
    invoice_currency = content["rsm:SupplyChainTradeTransaction"]["ram:ApplicableHeaderTradeSettlement"]["ram:InvoiceCurrencyCode"]
    lines = rget(content, "rsm:SupplyChainTradeTransaction.ram:IncludedSupplyChainTradeLineItem")
    if not lines:
        return []
    for line in lines:
        line_trade_settlement_obj = line["ram:SpecifiedLineTradeSettlement"]
        line_amount_obj = line_trade_settlement_obj["ram:SpecifiedTradeSettlementLineMonetarySummation"]["ram:LineTotalAmount"]
        if isinstance(line_amount_obj, dict):
            line_amount_excl_tax = Decimal(line_amount_obj["$"])
            line_price_currency = line_amount_obj["@currencyID"]
            assert line_price_currency == invoice_currency, f"Currency missmatch {invoice_currency} != {line_price_currency}"
        else:
            line_amount_excl_tax = Decimal(line_amount_obj)
        line_amount_tax = None
        if line_amount_excl_tax.is_zero():
            line_amount_tax = Decimal("0")
        else:
            applicable_trade_tax_obj = line_trade_settlement_obj["ram:ApplicableTradeTax"]
            tax_percent = applicable_trade_tax_obj["ram:RateApplicablePercent"]
            if isinstance(tax_percent, str):
                tax_percent = Decimal(tax_percent)
            elif isinstance(tax_percent, dict):
                tax_percent = Decimal(tax_percent["$"])
            else:
                raise ValueError(f"Invalid tax percent format {applicable_trade_tax_obj!r}")
            line_amount_tax = line_amount_excl_tax * tax_percent / Decimal("100")

        if line_amount_tax is None:
            raise ValueError(f"Cannot extract taxes from {id_cpro} {line!r}")

        line_amount_incl_tax = line_amount_excl_tax + line_amount_tax

        unit_price_obj = line["ram:SpecifiedLineTradeAgreement"]["ram:NetPriceProductTradePrice"]["ram:ChargeAmount"]
        if isinstance(unit_price_obj, dict):
            unit_price = Decimal(unit_price_obj["$"])
            unit_price_currency = unit_price_obj["@currencyID"]
            assert unit_price_currency == invoice_currency, f"Currency missmatch {invoice_currency} != {unit_price_currency}"
        else:
            unit_price = Decimal(unit_price_obj)

        quantity_obj = line["ram:SpecifiedLineTradeDelivery"]["ram:BilledQuantity"]
        if isinstance(quantity_obj, dict):
            quantity_unit_code = quantity_obj["@unitCode"]
            quantity = quantity_obj["$"]
        elif isinstance(quantity_obj, (str, int, float, Decimal)):
            quantity_unit_code = ""
            quantity = Decimal(quantity_obj)
        else:
            raise ValueError(f"Unknown quantity type {quantity_obj!r}")

        note_obj = rget(line, "ram:AssociatedDocumentLineDocument.ram:IncludedNote")
        if note_obj:
            item_description = "\n".join(x for x in note_obj["ram:Content"] if x) if note_obj is not None else ""
        else:
            item_description = ""

        try:
            result.append(
                SilverCproExportFacturXLigne(
                    id_cpro=id_cpro,
                    xml_schema=xml_schema,
                    line_id=line["ram:AssociatedDocumentLineDocument"]["ram:LineID"],
                    quantity_unit_code=quantity_unit_code,
                    quantity=quantity,
                    item_name=line["ram:SpecifiedTradeProduct"]["ram:Name"],
                    item_description=item_description,
                    item_reference=line["ram:SpecifiedTradeProduct"].get("ram:GlobalID"),
                    unit_price=unit_price,
                    line_amount_excl_tax=line_amount_excl_tax,
                    line_amount_incl_tax=line_amount_incl_tax,
                    line_amount_vat=line_amount_tax,
                    currency=invoice_currency,
                )
            )
        except Exception:
            print("Weird line", id_cpro, repr(line))
            raise

    # Ajout des lignes des charges (ex: livraison)
    for charge_idx, charge in enumerate(content["rsm:SupplyChainTradeTransaction"]["ram:ApplicableHeaderTradeSettlement"].get("ram:SpecifiedTradeAllowanceCharge", [])):
        amount = Decimal(charge["ram:ActualAmount"]["$"])
        # Fixe la TVA à 20%
        line_amount_tax = Decimal("0.2") * amount
        line_amount_excl_tax = amount
        line_amount_incl_tax = line_amount_excl_tax + line_amount_tax
        allowance_charge_reason = charge["ram:Reason"]
        result.append(
            SilverCproExportFacturXLigne(
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
                currency=charge["ram:ActualAmount"]["@currencyID"],
            )
        )
    return result


def transform_to_silver(
        bronze_factures_xml: list[BronzeCproExportFacturX],
) -> list[SilverCproExportFacturXLigne]:
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
