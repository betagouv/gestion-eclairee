import json
import logging
from decimal import Decimal

from tqdm import tqdm

from gesec.data.pipeline.db import load_rows_from_table, save_list_pydantic
from gesec.data.pipeline.layer_1_bronze.cpro_export_factur_x import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from gesec.data.pipeline.layer_1_bronze.schemas import BronzeCproExportFacturX
from gesec.data.pipeline.layer_2_silver.schemas import SilverCproExportFacturXLigne, SilverCproExportFacturXLigneStatus
from gesec.data.pipeline.utils import force_string, rget, xml_value

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]


def load_bronze_rows(table_name: str) -> list[BronzeCproExportFacturX]:
    return load_rows_from_table(table_name, BronzeCproExportFacturX)


def transform_xml_to_silver(content: dict, id_cpro: str, xml_schema: str) -> list[SilverCproExportFacturXLigne]:
    result = []
    invoice_currency = rget(
        content, "rsm:SupplyChainTradeTransaction.ram:ApplicableHeaderTradeSettlement.ram:InvoiceCurrencyCode"
    )
    lines = rget(content, "rsm:SupplyChainTradeTransaction.ram:IncludedSupplyChainTradeLineItem")
    if not lines:
        return []
    for line in lines:
        line_trade_settlement_obj = line["ram:SpecifiedLineTradeSettlement"]
        line_amount_obj = line_trade_settlement_obj["ram:SpecifiedTradeSettlementLineMonetarySummation"][
            "ram:LineTotalAmount"
        ]
        if isinstance(line_amount_obj, dict):
            line_amount_excl_tax = Decimal(line_amount_obj["$"])
            line_price_currency = line_amount_obj["@currencyID"]
            if line_price_currency == "XXX":
                line_price_currency = None
            if not invoice_currency:
                invoice_currency = line_price_currency
            assert not line_price_currency or line_price_currency == invoice_currency, (
                f"Currency missmatch {invoice_currency!r} != {line_price_currency!r}"
            )
        else:
            line_amount_excl_tax = Decimal(line_amount_obj)
        line_amount_tax = None
        if line_amount_excl_tax.is_zero():
            line_amount_tax = Decimal("0")
        else:
            tax_percent_obj = rget(line_trade_settlement_obj, "ram:ApplicableTradeTax.ram:RateApplicablePercent")
            if tax_percent_obj is not None:
                if isinstance(tax_percent_obj, str):
                    tax_percent = Decimal(tax_percent_obj)
                elif isinstance(tax_percent_obj, dict):
                    tax_percent = Decimal(tax_percent_obj["$"])
                else:
                    raise ValueError(f"Invalid tax percent format {tax_percent_obj!r}")
                line_amount_tax = line_amount_excl_tax * tax_percent / Decimal("100")

        # Essaie d'extraire la tva depuis les taux globaux de la facture
        # Ne marche que s'il y a une seule TVA
        if line_amount_tax is None:
            trade_taxes = rget(
                content, "rsm:SupplyChainTradeTransaction.ram:ApplicableHeaderTradeSettlement.ram:ApplicableTradeTax"
            )
            if trade_taxes and len(trade_taxes) == 1:
                tax_percent = trade_taxes[0].get("ram:RateApplicablePercent")
                if tax_percent:
                    tax_percent = Decimal(tax_percent)
                    line_amount_tax = line_amount_excl_tax * tax_percent / Decimal("100")

        # Essaie d'extraire la tva depuis le montant total de la facture
        # Ne marche que s'il y a une seule TVA
        if line_amount_tax is None:
            header_summation = rget(
                content,
                "rsm:SupplyChainTradeTransaction.ram:ApplicableHeaderTradeSettlement.ram:SpecifiedTradeSettlementHeaderMonetarySummation",
            )
            if header_summation:
                tax_total = header_summation.get("ram:TaxTotalAmount")
                tax_basis_total = header_summation.get("ram:TaxBasisTotalAmount")
                if tax_total and tax_basis_total:
                    tax_total = Decimal(xml_value(tax_total[0] if isinstance(tax_total, list) else tax_total))
                    tax_basis_total = Decimal(xml_value(tax_basis_total))
                    if not tax_total.is_zero():
                        tax_percent = tax_basis_total / tax_total
                        line_amount_tax = line_amount_excl_tax * tax_percent / Decimal("100")

        if line_amount_tax is None:
            raise ValueError(f"Cannot extract taxes from {id_cpro} {line!r}")

        line_amount_incl_tax = line_amount_excl_tax + line_amount_tax

        unit_price_obj = line["ram:SpecifiedLineTradeAgreement"]["ram:NetPriceProductTradePrice"]["ram:ChargeAmount"]
        if isinstance(unit_price_obj, dict):
            unit_price = Decimal(unit_price_obj["$"])
            unit_price_currency = unit_price_obj["@currencyID"]
            if unit_price_currency == "XXX":
                unit_price_currency = None
            if not invoice_currency:
                invoice_currency = unit_price_currency
            assert not unit_price_currency or unit_price_currency == invoice_currency, (
                f"Currency missmatch {invoice_currency} != {unit_price_currency}"
            )
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

        note_obj = rget(line, "ram:AssociatedDocumentLineDocument.ram:IncludedNote.ram:Content")
        if note_obj:
            item_description = force_string(note_obj, sep="\n")
        else:
            item_description = ""

        item_name = rget(line, "ram:SpecifiedTradeProduct.ram:Name") or ""
        item_reference = rget(line, "ram:SpecifiedTradeProduct.ram:GlobalID")
        if not item_name:
            if item_description:
                item_name = item_description.split("\n")[0]

        try:
            result.append(
                SilverCproExportFacturXLigne(
                    id_cpro=id_cpro,
                    xml_schema=xml_schema,
                    line_id=line["ram:AssociatedDocumentLineDocument"]["ram:LineID"],
                    quantity_unit_code=quantity_unit_code,
                    quantity=quantity,
                    item_name=item_name,
                    item_description=item_description,
                    item_reference=item_reference,
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
    for charge_idx, charge in enumerate(
        content["rsm:SupplyChainTradeTransaction"]["ram:ApplicableHeaderTradeSettlement"].get(
            "ram:SpecifiedTradeAllowanceCharge", []
        )
    ):
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
) -> tuple[list[SilverCproExportFacturXLigne], list[SilverCproExportFacturXLigneStatus]]:
    result = []
    status_list = []
    for fac in tqdm(bronze_factures_xml):
        try:
            lines = transform_xml_to_silver(fac.content, fac.id_cpro, fac.xml_schema)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"Cannot transform {fac.id_cpro} to silver: {e!r}")
            status_list.append(
                SilverCproExportFacturXLigneStatus(
                    id_cpro=fac.id_cpro,
                    status="Error",
                    status_details=repr(e),
                )
            )
        else:
            result.extend(lines)
            status_list.append(
                SilverCproExportFacturXLigneStatus(
                    id_cpro=fac.id_cpro,
                    status="Ok",
                )
            )
    return result, status_list


def process_to_silver(
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
    silver_table_name: str = DEFAULT_TABLE_NAME,
) -> None:
    bronze_factures = load_bronze_rows(bronze_table_name)
    silver_lines, silver_lines_status = transform_to_silver(bronze_factures)
    save_list_pydantic(silver_lines, silver_table_name, if_exists="replace")
    save_list_pydantic(silver_lines_status, silver_table_name + "_status", if_exists="replace")
