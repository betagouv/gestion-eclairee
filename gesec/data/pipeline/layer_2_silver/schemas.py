from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel


class SilverCproExportFacture(BaseModel):
    """Facture dédupliquée de la couche Silver (1 ligne par identifiant_chorus_pro)."""

    # Source tracking
    source: str
    source_idx: int

    # Identification
    identifiant_chorus_pro: str
    numero: str

    # État
    etat_courant: Optional[str] = None
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
    date_etat_courant: Optional[date] = None
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
    certificat_de_depot_numero: Optional[str] = None
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


CproExportFactureStatus = Literal["Ok", "Validation error", "Duplicat"]


class SilverCproExportFactureProcessingStatus(BaseModel):
    """Suivi de l'état de traitement d'une facture bronze."""

    identifiant_chorus_pro: Optional[str]
    status: CproExportFactureStatus
    status_details: Optional[str]


class SilverService(BaseModel):
    code: str
    name: str
    ministere: Optional[str] = None


class SilverOdaExportEjGmMapping(BaseModel):
    """Correspondance (EJ, GM) distincte extraite de l'export ODA."""

    domaine: Optional[str] = None
    domaine_libelle: Optional[str] = None
    segment: Optional[str] = None
    libelle_du_segment: Optional[str] = None
    groupe_de_marchandises_p_cle: Optional[str] = None
    gdm_libelle: Optional[str] = None
    numero_ej_reference_facture: Optional[str] = None


class SilverCproExportFacturXLigne(BaseModel):
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


CproExportFacturXLigneStatus = Literal["Ok", "Error"]


class SilverCproExportFacturXLigneStatus(BaseModel):
    id_cpro: str
    status: CproExportFacturXLigneStatus
    status_details: Optional[str] = None


class SilverUgapExportFacture(BaseModel):
    """Ligne nettoyée d'un export Excel de factures UGAP."""

    # Source tracking
    source: str
    source_idx: str
    onglet: str

    numero_commande_ugap: str
    numero_commande_chez_le_client: str = ""
    numero_facture: str = ""
    jour_creation_commande_ugap: date
    jour_paiement_commande_ugap: date
    univers_clients_ugap: str
    code_donneur_d_ordre: str
    ministere: str
    part_nom_1_organ: str
    part_nom_2_organ: str = ""
    siren: str
    sae_niveau_3: str = ""
    sae_niveau_4: str = ""
    ac_se_bp_operateur_etat: str = ""
    code_gm: str
    designation_gm: str
    marche_numero: str
    type_offre_logicielle: str = ""
    code_lot: str
    designation_du_lot: str
    designation_titulaire_marche: str
    siren_titulaire_1: str
    pays_titulaire_1: str = ""
    type_entreprise_titulaire_1: str
    code_article_ugap: str
    constructeur_article: str = ""
    titulaire_rang_2: str = ""
    pays_titulaire_2: str = ""
    type_ent_titulaire_2: str = ""
    siren_titulaire_2: str = ""
    sous_traitant: str = ""
    pays_ss_traitant: str = ""
    type_ent_ss_traitant: str = ""
    siren_ss_traitant: str = ""
    article_numero_vue_adv: str
    texte_adv_ligne_1: str = ""
    texte_adv_ligne_2: str = ""
    texte_adv_ligne_3: str = ""
    texte_adv_ligne_4: str = ""
    ce_ht: Decimal
    tva: Decimal
    ce_ttc: Decimal
    qte_article_commandee: Decimal
    montant_facture_ht: Optional[Decimal] = None


UgapExportFactureStatus = Literal["Ok", "Validation error", "Duplicat"]


class SilverUgapExportFactureStatus(BaseModel):
    """Suivi de l'état de traitement d'une ligne bronze d'export UGAP."""

    source: str
    source_idx: str
    status: UgapExportFactureStatus
    status_details: Optional[str] = None


class SilverCproExportFactureXmlFacture(BaseModel):
    id_cpro: str
    xml_schema: str
    numero: str
    delivery: Optional[Any] = None
    delivery_id: Optional[str] = None
    note: str = ""


CproExportFactureXmlFactureStatus = Literal["Ok", "Error"]


class SilverCproExportFactureXmlFactureStatus(BaseModel):
    id_cpro: str
    status: CproExportFactureXmlFactureStatus
    status_details: Optional[str] = None


class SilverCproExportFactureXmlLigne(BaseModel):
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
