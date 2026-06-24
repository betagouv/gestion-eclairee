from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from ..layer_1_bronze.schemas import BronzeCproExportFacture


class SilverCproExportFacture(BaseModel):
    """Facture dédupliquée de la couche Silver (1 ligne par identifiant_chorus_pro)."""

    # Source tracking
    source: str
    source_idx: int

    # Identification
    identifiant_chorus_pro: str
    numero: str

    # État
    etat_courant: str = None
    instructeur: Optional[str] = None
    motif_de_rejet: Optional[str] = None
    commentaire_de_l_etat: Optional[str] = None

    # Types
    type_de_demande_de_paiement: Optional[str] = None
    type_facture: Optional[str] = None
    type_de_facture_de_travaux: Optional[str] = None
    cadre_de_facturation: Optional[str] = None

    # Dates
    date_fournisseur: Optional[date] = None
    date_de_creation: Optional[date] = None
    date_de_depot: Optional[date] = None
    date_etat_courant: date = None
    date_echeance_paiement: Optional[date] = None
    valideur_1_date_de_validation: Optional[date] = None
    valideur_2_date_de_validation: Optional[date] = None
    date_modification: date

    # Fournisseur
    fournisseur_type_d_identifiant: str
    fournisseur_identifiant: str
    fournisseur_designation: str
    fournisseur_tva_intracommunautaire: Optional[str] = None
    fournisseur_code_service: Optional[str] = None
    fournisseur_service: Optional[str] = None

    # Destinataire
    destinataire_type_d_identifiant: str
    destinataire_identifiant: str
    destinataire_designation: str
    destinataire_tva_intracommunautaire: Optional[str] = None
    destinataire_code_service: str
    destinataire_service: str

    # Mode
    mode_de_depot: Optional[str] = None

    # Montants
    mt_ht: Decimal
    mt_ttc: Decimal
    montant_a_payer: Decimal
    montant_ttc_avant_remise: Optional[Decimal] = None
    montant_remise_globale_ttc: Optional[Decimal] = None
    montant_tva: Optional[Decimal] = None

    # Autres champs
    motif: Optional[str] = None
    devise_de_la_facture: str
    type_de_tva: Optional[str] = None
    motif_d_exoneration: Optional[str] = None
    certificat_de_depot_ndeg: Optional[str] = None
    identifiant_numerisation: Optional[str] = None

    # Numéros de référence
    numero_de_la_facture_d_origine: Optional[str] = None
    numero_dp_mandat: Optional[str] = None
    numero_du_bon_de_commande: str
    numero_de_marche: str

    # Coordonnées bancaires
    coordonnees_bancaires: Optional[str] = None
    bic_ou_swift: Optional[str] = None
    mode_de_reglement: Optional[str] = None

    # Documents
    document_precedent_numero: Optional[str] = None
    document_precedent_type_de_piece: Optional[str] = None
    document_suivant_numero: Optional[str] = None
    document_suivant_type_de_piece: Optional[str] = None

    # Dossier
    dossier_de_facturation: Optional[str] = None
    commentaire: Optional[str] = None
    numero_de_lot_transmis: Optional[str] = None

    # Statut
    telechargee: Optional[str] = None

    # Émetteur
    emetteur_type_d_identifiant: Optional[str] = None
    emetteur_identifiant: Optional[str] = None
    emetteur_designation: Optional[str] = None

    # Affactureur
    affactureur_type_d_identifiant: Optional[str] = None
    affactureur_identifiant: Optional[str] = None
    affactureur_designation: Optional[str] = None

    # Maîtrise d'œuvre
    maitrise_d_oeuvre_type_d_identifiant: Optional[str] = None
    maitrise_d_oeuvre_identifiant: Optional[str] = None
    maitrise_d_oeuvre_designation: Optional[str] = None
    maitrise_d_oeuvre_tva_intracommunautaire: Optional[str] = None
    maitrise_d_oeuvre_code_service: Optional[str] = None
    maitrise_d_oeuvre_service: Optional[str] = None

    # Maîtrise d'ouvrage
    maitrise_d_ouvrage_type_d_identifiant: Optional[str] = None
    maitrise_d_ouvrage_identifiant: Optional[str] = None
    maitrise_d_ouvrage_designation: Optional[str] = None
    maitrise_d_ouvrage_tva_intracommunautaire: Optional[str] = None
    maitrise_d_ouvrage_code_service: Optional[str] = None
    maitrise_d_ouvrage_service: Optional[str] = None

    # Valideurs
    valideur_1_type_d_identifiant: Optional[str] = None
    valideur_1_identifiant: Optional[str] = None
    valideur_1_designation: Optional[str] = None
    valideur_2_type_d_identifiant: Optional[str] = None
    valideur_2_identifiant: Optional[str] = None
    valideur_2_designation: Optional[str] = None


class SilverCproExportFactureProcessingStatus(BronzeCproExportFacture):
    """Suivi de l'état de traitement d'une facture bronze."""

    status: str
    status_details: Optional[str]


class SilverService(BaseModel):
    code: str
    name: str
    ministere: Optional[str] = None
