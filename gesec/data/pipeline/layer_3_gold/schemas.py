from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class GoldCproExportFactureLigne(BaseModel):
    id_cpro: str
    source: str
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


class FactureLigne(BaseModel):
    nom: str
    description: str
    reference: Optional[str]
    quantite: float
    quantite_code_unitaire: Optional[str]
    prix_unitaire: Optional[float]
    montant_ttc: Optional[float]
    montant_ht: Optional[float]
    montant_tva: Optional[float]


class Facture(BaseModel):
    reference: str
    date_emission: date
    date_echeance: Optional[date]
    numero_engagement: Optional[str]
    numero_marche: Optional[str]
    numero_bon_de_commande: Optional[str]
    code_devise_facture: str

    emetteur_nom: str
    emetteur_adresse: Optional[str]
    emetteur_numero_immatriculation: Optional[str]
    emetteur_numero_tva: Optional[str]
    emetteur_code_naf: Optional[str]

    destinataire_num: str
    destinataire_adresse: Optional[str]
    destinataire_numero_immatriculation: Optional[str]
    destinataire_numero_tva: Optional[str]
    destinataire_code_service: Optional[str]

    montant_ht: float
    montant_ttc: float
    montant_tva: float
    montant_ttc_avant_remise: Optional[float]
    montant_remise_globale_ttc: Optional[float]

    lignes: list[FactureLigne]
