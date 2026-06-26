from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class GoldCproExportFactureLigne(BaseModel):
    id_cpro: str
    xml_schema: str
    line_id: str
    item_name: str
    item_description: str
    item_reference: Optional[str]
    quantity: Decimal
    quantity_unit_code: str
    unit_price: Decimal
    line_amount_excl_tax: Decimal
    line_amount_incl_tax: Decimal
    line_amount_vat: Decimal
    currency: str
