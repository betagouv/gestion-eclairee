from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class BronzeCproExportFacture(BaseModel):
    """Facture importée depuis un export csv de Chorus Pro."""

    # Source tracking
    source: str
    source_idx: int

    # Identification
    identifiant_chorus_pro: Optional[str]
    numero: Optional[str]

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
    date_modification: Optional[date] = None

    # Fournisseur
    fournisseur_type_d_identifiant: Optional[str] = None
    fournisseur_identifiant: Optional[str] = None
    fournisseur_designation: Optional[str] = None
    fournisseur_tva_intracommunautaire: Optional[str] = None
    fournisseur_code_service: Optional[str] = None
    fournisseur_service: Optional[str] = None

    # Destinataire
    destinataire_type_d_identifiant: Optional[str] = None
    destinataire_identifiant: Optional[str] = None
    destinataire_designation: Optional[str] = None
    destinataire_tva_intracommunautaire: Optional[str] = None
    destinataire_code_service: Optional[str] = None
    destinataire_service: Optional[str] = None

    # Mode
    mode_de_depot: Optional[str] = None

    # Montants
    mt_ht: Optional[Decimal] = None
    mt_ttc: Optional[Decimal] = None
    montant_a_payer: Optional[Decimal] = None
    montant_ttc_avant_remise: Optional[Decimal] = None
    montant_remise_globale_ttc: Optional[Decimal] = None
    montant_tva: Optional[Decimal] = None

    # Autres champs
    motif: Optional[str] = None
    devise_de_la_facture: Optional[str] = None
    type_de_tva: Optional[str] = None
    motif_d_exoneration: Optional[str] = None
    certificat_de_depot_numero: Optional[str] = Field(default=None, validation_alias="certificat_de_depot_ndeg")
    identifiant_numerisation: Optional[str] = None

    # Numéros de référence
    numero_de_la_facture_d_origine: Optional[str] = None
    numero_dp_mandat: Optional[str] = None
    numero_du_bon_de_commande: Optional[str] = None
    numero_de_marche: Optional[str] = None

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


class BronzeODAExportRow(BaseModel):
    """Données importées depuis un export CSV ODA."""

    # Source tracking
    source: str
    source_idx: int

    # Domaine
    domaine: str = Field(validation_alias="Domaine")
    domaine_libelle: str = Field(validation_alias="Domaine libellé")

    # Segment
    segment: str = Field(validation_alias="Segment")
    libelle_du_segment: str = Field(validation_alias="Libellé du segment")

    # Groupe de marchandises
    groupe_de_marchandises_p_cle: str = Field(validation_alias="Groupe de marchandises (P) - Clé")
    gdm_libelle: str = Field(validation_alias="GdM_Libellé ")

    # Ministère
    ministere: str = Field(validation_alias="Ministère")
    v_ministere_service_beneficaire: Optional[str] = Field(
        default=None, validation_alias="V_Ministère_Service bénéficaire"
    )

    # Région
    v_region_dae_carto: Optional[str] = Field(default=None, validation_alias="V_Région_DAE_Carto")
    region_cartographie_detaillee: Optional[str] = Field(default=None, validation_alias="Région Cartographie détaillée")
    region_cartographie_regroupee: Optional[str] = Field(default=None, validation_alias="Région Cartographie regroupée")

    # Programme
    prog_bop: Optional[str] = Field(default=None, validation_alias="Prog-BOP")
    cf: Optional[str] = Field(default=None, validation_alias="CF")

    # Centre de coûts
    centre_de_couts_p_cle_non_composee: Optional[str] = Field(
        default=None, validation_alias="Centre de coûts (P) - Clé (non composée)"
    )

    # Direction
    direction: Optional[str] = Field(default=None, validation_alias="Direction")

    # Compte général
    compte_general_p_cle_non_composee: Optional[str] = Field(
        default=None, validation_alias="Compte général (P) - Clé (non composée)"
    )
    compte_general_p: Optional[str] = Field(default=None, validation_alias="Compte général (P)")

    # Fournisseur
    nom_fournisseur_cle: Optional[str] = Field(default=None, validation_alias="Nom fournisseur - Clé")
    siren_fournisseur: Optional[str] = Field(default=None, validation_alias="SIREN fournisseur")
    type_de_fournisseur: Optional[str] = Field(default=None, validation_alias="Type de fournisseur")
    code_naf_fournisseur_siren: Optional[str] = Field(default=None, validation_alias="Code NAF fournisseur (SIREN)")
    pays_fournisseur: Optional[str] = Field(default=None, validation_alias="Pays fournisseur")
    region_fournisseur: Optional[str] = Field(default=None, validation_alias="Région fournisseur")
    v_region_insee_fournisseur: Optional[str] = Field(default=None, validation_alias="V_région INSEE Fournisseur")
    categorie_d_entreprise: Optional[str] = Field(default=None, validation_alias="Catégorie d'entreprise")
    type_fournisseur_ea: Optional[str] = Field(default=None, validation_alias="Type fournisseur EA")
    type_fournisseur_siae: Optional[str] = Field(default=None, validation_alias="Type fournisseur SIAE")
    role_partenaire_fournisseur_p: Optional[str] = Field(
        default=None, validation_alias="Rôle partenaire fournisseur (P)"
    )
    schema_regroupement_partenaire_e: Optional[str] = Field(
        default=None, validation_alias="Schéma regroupement partenaire (E)"
    )

    # Opération
    type_d_operation_ej_precedent_e: Optional[str] = Field(
        default=None, validation_alias="Type d'opération EJ précédent (E)"
    )
    macro_type_ej_notifie_ou_non: Optional[str] = Field(default=None, validation_alias="Macro Type EJ Notifié ou non")
    notifie: Optional[str] = Field(default=None, validation_alias="Notifié ?")

    # Accord-cadre
    numero_accord_cadre_e_cle: Optional[str] = Field(default=None, validation_alias="Numéro accord-cadre (E) - Clé")
    numero_accord_cadre_e_texte_descriptif: Optional[str] = Field(
        default=None, validation_alias="Numéro accord-cadre (E) - Texte descriptif"
    )

    # EJ (Engagement Juridique)
    numero_ej_precedent_p: Optional[str] = Field(default=None, validation_alias="Numéro EJ précédent (P)")
    numero_ej_reference_facture: Optional[str] = Field(default=None, validation_alias="Numéro EJ référencé facture")

    # Clauses
    clause_environnementale_e: Optional[str] = Field(default=None, validation_alias="Clause environnementale (E)")
    clause_sociale_e: Optional[str] = Field(default=None, validation_alias="Clause sociale (E)")

    # CPV
    code_cpv_principal_e: Optional[str] = Field(default=None, validation_alias="Code CPV principal (E)")

    # Description
    description_de_l_ej: Optional[str] = Field(default=None, validation_alias="Description de l'EJ")

    # Dates
    date_notification_e: Optional[date] = Field(default=None, validation_alias="Date notification (E)")
    date_fin_de_marche_e: Optional[date] = Field(default=None, validation_alias="Date fin de marché (E)")

    # Acheteur
    siret_acheteur_e_cle: Optional[str] = Field(default=None, validation_alias="SIRET acheteur (E) - Clé")
    siret_acheteur_e_texte_descriptif: Optional[str] = Field(
        default=None, validation_alias="SIRET acheteur (E) - Texte descriptif"
    )

    # Montant
    depenses_2025: Decimal = Field(validation_alias="Dépenses  2025")


class BronzeCproExportFactureXml(BaseModel):
    id_cpro: str
    xml_schema: str
    content: dict


CproExportFactureXmlStatus = Literal["Ok", "Validation error", "Unexpected error"]


class BronzeCproExportFactureXmlStatus(BaseModel):
    id_cpro: str
    status: CproExportFactureXmlStatus
    status_details: Optional[str] = None


class BronzeCproExportFacturX(BaseModel):
    id_cpro: str
    xml_schema: str
    content: dict
    errors: str


class BronzeCproExportFacturXStatus(BaseModel):
    id_cpro: str
    status: str
    status_details: Optional[str] = None


class BronzeCproAnnuaireService(BaseModel):
    model_config = ConfigDict(validate_by_alias=True, validate_by_name=True)

    # Source tracking
    source: str
    source_idx: int

    # Fields
    identifiant: str = Field(validation_alias="Identifiant")
    designation: str = Field(validation_alias="Désignation")
    libelle_service: str = Field(validation_alias="Libelle service")
    code_service: str = Field(validation_alias="Code service")
    statut: str = Field(validation_alias="Statut")
    service_obligatoire: str = Field(validation_alias="Service obligatoire")
    engagement_obligatoire: str = Field(validation_alias="Engagement obligatoire")
    service_ou_engagement_obligatoire: str = Field(validation_alias="Service ou engagement obligatoire")
    numero_tva: str = Field(validation_alias="Numéro TVA intracommunautaire")


class BronzeUgapExportFacture(BaseModel):
    """Ligne brute importée depuis un export Excel de factures UGAP."""

    model_config = ConfigDict(validate_by_alias=True, validate_by_name=True)

    # Source tracking
    source: str
    source_idx: str
    onglet: str

    cde_client_numero: str = Field(validation_alias="Cde Client - N°")
    cde_client_numero_cde_chez_le_client: str = Field(validation_alias="Cde Client - N° cde chez le client")
    cde_client_jour_de_creation: str = Field(validation_alias="Cde client - Jour de création")
    cde_client_date_paiement_client: str = Field(validation_alias="Cde client - Date Paiement client")
    compte_crm_do_univers_bp: str = Field(validation_alias="Compte CRM DO - Univers BP")
    compte_crm_numero_donneur_d_ordre: str = Field(validation_alias="Compte CRM - N° donneur d'ordre")
    ministere: str = Field(validation_alias="Ministère")
    part_nom_1_organ: str = Field(validation_alias="Part.: nom 1 organ.")
    part_nom_2_organ: str = Field(validation_alias="Part.: nom 2 organ.")
    siren: str = Field(validation_alias="SIREN")
    inclus: str = Field(validation_alias="Inclus")
    sae_niveau_3: str = Field(validation_alias="SAE Niveau 3")
    sae_niveau_4: str = Field(validation_alias="SAE Niveau 4")
    ac_se_bp_operateur_etat: str = Field(validation_alias="AC/SE (BP operateur état)")
    code_gm: str = Field(validation_alias="Code GM")
    designation_gm: str = Field(validation_alias="Désignation GM")
    marche_numero: str = Field(validation_alias="Marché - N°")
    type_d_offre_logiciels: str = Field(validation_alias="Type d'offre Logiciels")
    article_code_lot: str = Field(validation_alias="Article - Code Lot")
    designation_du_lot: str = Field(validation_alias="Désignation du Lot")
    article_code_fourniseur: str = Field(validation_alias="Article - Code fourniseur")
    siren_titulaire: str = Field(validation_alias="SIREN Titulaire")
    boa_tete_de_groupe_mondiale_pays: str = Field(validation_alias="BOA - Tête de groupe mondiale - Pays")
    type_entreprise_tpe_pme_pmi_eti_grande_entreprise: str = Field(
        validation_alias="Type Entreprise: TPE/PME-PMI/ETI/Grande Entreprise"
    )
    article_numero: str = Field(validation_alias="Article - N°")
    constructeur_hardware_ajout_manuel: str = Field(validation_alias="Constructeur (hardware ajout manuel)")
    titulaire_2_editeurs_multi_editeurs: str = Field(validation_alias="Titulaire 2 (Editeurs Multi Editeurs)")
    siren_titulaire_2: str = Field(validation_alias="Siren Titulaire 2")
    pays_du_titualire_2: str = Field(validation_alias="Pays du Titualire 2")
    type_ent_titulaire_2: str = Field(validation_alias="Type ent Titulaire 2")
    sous_traitant_sur_marches_presta: str = Field(validation_alias="Sous Traitant (sur marchés Presta)")
    siren_ss_traitant: str = Field(validation_alias="Siren Ss Traitant")
    pays_ss_traitant: str = Field(validation_alias="Pays Ss Traitant")
    type_ent_ss_traitant: str = Field(validation_alias="Type ent Ss Traitant")
    article_numero_vue_adv: str = Field(validation_alias="Article - N° (vue ADV)")
    texte_adv_ligne_1: str = Field(validation_alias="Texte ADV ligne 1")
    texte_adv_ligne_2: str = Field(validation_alias="Texte ADV ligne 2")
    texte_adv_ligne_3: str = Field(validation_alias="Texte ADV ligne 3")
    texte_adv_ligne_4: str = Field(validation_alias="Texte ADV ligne 4")
    ce_ht: Decimal = Field(validation_alias="CE HT")
    tva_collectee: Decimal = Field(validation_alias="TVA Collectée")
    ce_ttc: Decimal = Field(validation_alias="CE TTC")
    qte_commandees: Decimal = Field(validation_alias="Qté commandées")
    montant_facture_ht: Decimal = Field(validation_alias="Montant Facturé HT")


class BronzeBudatExportAugdt(BaseModel):
    model_config = ConfigDict(validate_by_alias=True, validate_by_name=True)

    # Source tracking
    source: str
    source_idx: int

    annee: str = Field(validation_alias="ANNEE")
    facture: str = Field(validation_alias="FACTURE")
    facture_ref: str = Field(validation_alias="REF_FAC")
    facture_date: str = Field(validation_alias="DATE_FAC")
    facture_montant: str = Field(validation_alias="MNT_FAC")
    date_payment: str = Field(validation_alias="DATE_PY")
    ej: str = Field(validation_alias="EJ")
    marche: str = Field(validation_alias="MARCHE")
    seej: str = Field(validation_alias="SEEJ")
    gm: str = Field(validation_alias="GM")
    libelle: str = Field(validation_alias="LIBELLE")
    fournisseur: str = Field(validation_alias="FOURN")
    fournisseur_siren: str = Field(validation_alias="SIREN")
    facture_fi: str = Field(validation_alias="FACTURE_FI")
    societe: str = Field(validation_alias="SOCIETE")
    service: str = Field(validation_alias="SEDP")
    cc: str = Field(validation_alias="CC")
    pce: str = Field(validation_alias="PCE")
    txt50: str = Field(validation_alias="TXT50")
    activite: str = Field(validation_alias="ACTIVIT")
    description: str = Field(validation_alias="DESCRIPTION")
