from datetime import date
from decimal import Decimal
from typing import Any

from gesec.data.pipeline.layer_2_silver.schemas import SilverCproExportFacture, SilverUgapExportFacture
from gesec.data.pipeline.layer_3_gold.constants import UGAP_SIREN
from gesec.data.pipeline.layer_3_gold.facture_ligne import (
    build_ugap_ligne,
    enrich_existing_lines,
    is_ugap_facture,
    match_ugap,
    normalize_reference,
    resolve_fournisseur_in_fine,
)
from gesec.data.pipeline.layer_3_gold.schemas import GoldCproExportFactureLigne


def silver_facture(
    numero: str = "A1",
    id_cpro: str = "cpro-1",
    fournisseur_identifiant: str = UGAP_SIREN,
) -> SilverCproExportFacture:
    return SilverCproExportFacture(
        source="cpro/exports/f.csv",
        source_idx=0,
        identifiant_chorus_pro=id_cpro,
        numero=numero,
        date_modification=date(2025, 1, 1),
        fournisseur_type_d_identifiant="SIREN",
        fournisseur_identifiant=fournisseur_identifiant,
        fournisseur_designation="UGAP",
        destinataire_type_d_identifiant="Structure avec N° SIRET",
        destinataire_identifiant="11000201100044",
        destinataire_designation="SERVICES DE L'ETAT POUR LA FACTURATION ELECTRONIQUE",
        destinataire_code_service="SERVICE",
        destinataire_service="Service",
        mt_ht=Decimal("100"),
        mt_ttc=Decimal("120"),
        montant_a_payer=Decimal("120"),
        devise_de_la_facture="EUR",
        numero_du_bon_de_commande="BC",
        numero_de_marche="MARCHE",
    )


def silver_ugap_line(
    line_id: int = 1,
    numero: str = "A1",
    article: str = "Y1",
    **overrides: Any,
) -> SilverUgapExportFacture:
    values: dict[str, Any] = dict(
        source="ugap/f.xlsx",
        source_idx=f"11_2025_dinum_{line_id}",
        onglet="11 2025 - Dinum",
        line_id=line_id,
        cde_client_numero=numero,
        article_numero=article,
        cde_client_jour_de_creation=date(2025, 4, 10),
        cde_client_date_paiement_client=date(2025, 11, 6),
        compte_crm_do_univers_bp="ETABLISSEMENTS PUBLICS",
        compte_crm_numero_donneur_d_ordre="99082863",
        ministere="M.CUL",
        part_nom_1_organ="MUSEE ORSAY",
        siren="180092447",
        inclus="Oui",
        code_gm="33.01.04",
        designation_gm="Services téléphonie fixe",
        marche_numero="616024",
        article_code_lot="LOT/001",
        designation_du_lot="Désignation lot",
        article_code_fourniseur="FOURNISSEUR",
        siren_titulaire="343059564",
        type_entreprise_tpe_pme_pmi_eti_grande_entreprise="Grande Entreprise",
        article_numero_vue_adv="Article 1",
        texte_adv_ligne_1="Texte 1",
        ce_ht=Decimal("100"),
        tva_collectee=Decimal("20"),
        ce_ttc=Decimal("120"),
        qte_commandees=Decimal("2"),
        montant_facture_ht=Decimal("100"),
    )
    values.update(overrides)
    return SilverUgapExportFacture(**values)


def gold_line(
    id_cpro: str = "cpro-1",
    line_id: str = "1",
    item_reference: str = "Y1",
    **overrides: Any,
) -> GoldCproExportFactureLigne:
    values: dict[str, Any] = dict(
        id_cpro=id_cpro,
        source="facture-xml",
        xml_schema="UBL-Invoice-2",
        line_id=line_id,
        item_name="Article",
        item_description="Description",
        item_reference=item_reference,
        quantity=Decimal("1"),
        quantity_unit_code="",
        unit_price=Decimal("100"),
        line_amount_excl_tax=Decimal("100"),
        line_amount_incl_tax=Decimal("120"),
        line_amount_vat=Decimal("20"),
        currency="EUR",
    )
    values.update(overrides)
    return GoldCproExportFactureLigne(**values)


def test_normalize_reference():
    assert normalize_reference(None) is None
    assert normalize_reference("  ") is None
    assert normalize_reference(" 5650607 ") == "5650607"
    assert normalize_reference("005650607") == "5650607"
    assert normalize_reference("0") == "0"
    assert normalize_reference("ABC/001") == "ABC/001"


def test_is_ugap_facture():
    assert is_ugap_facture(UGAP_SIREN) is True
    assert is_ugap_facture(f"{UGAP_SIREN}0001") is True
    assert is_ugap_facture("123456789") is False
    assert is_ugap_facture(None) is False


def test_resolve_fournisseur_in_fine_fallbacks():
    line = silver_ugap_line(
        titulaire_2_editeurs_multi_editeurs="TITULAIRE 2",
        constructeur_hardware_ajout_manuel="CONSTRUCTEUR",
        siren_titulaire_2="111111111",
    )
    assert resolve_fournisseur_in_fine(line) == ("TITULAIRE 2", "111111111")

    line = silver_ugap_line(constructeur_hardware_ajout_manuel="CONSTRUCTEUR")
    assert resolve_fournisseur_in_fine(line) == ("CONSTRUCTEUR", "343059564")

    line = silver_ugap_line()
    assert resolve_fournisseur_in_fine(line) == ("FOURNISSEUR", "343059564")

    line = silver_ugap_line(article_code_fourniseur="", siren_titulaire="")
    assert resolve_fournisseur_in_fine(line) == (None, None)


def test_build_ugap_ligne():
    line = silver_ugap_line(line_id=3, numero="A9", article="Y9")

    suivi = build_ugap_ligne(line, "ligne_absente", id_cpro="cpro-1")

    assert suivi.source == "ugap/f.xlsx"
    assert suivi.source_idx == "11_2025_dinum_3"
    assert suivi.id_cpro == "cpro-1"
    assert suivi.numero_ugap == "A9"
    assert suivi.line_id == ""
    assert suivi.article_numero == "Y9"
    assert suivi.status == "ligne_absente"
    assert suivi.status_details is None

    suivi = build_ugap_ligne(line, "matched", id_cpro="cpro-1", line_id="4")

    assert suivi.line_id == "4"
    assert suivi.status == "matched"


def test_enrich_existing_lines_returns_consumed():
    lines = [
        gold_line(line_id="1", item_reference="Y1"),
        gold_line(line_id="2", item_reference="Y2"),
    ]
    ugap_lines = [silver_ugap_line(line_id=1, article="Y1"), silver_ugap_line(line_id=2, article="Y3")]

    enriched, consumed = enrich_existing_lines(lines, ugap_lines)

    assert [line.line_id for line in enriched] == ["1", "2"]
    assert enriched[0].fournisseur_in_fine_designation == "FOURNISSEUR"
    assert enriched[0].fournisseur_in_fine_siren == "343059564"
    assert enriched[1].fournisseur_in_fine_designation is None
    assert consumed == {("ugap/f.xlsx", "11_2025_dinum_1"): "1"}


def test_match_ugap_without_gold_lines_flags_ligne_absente():
    factures = [silver_facture(numero="A1", id_cpro="cpro-1")]
    ugap_lines = [silver_ugap_line(line_id=1, numero="A1", article="Y1")]

    lines, suivi = match_ugap(factures, [], ugap_lines)

    assert lines == []
    assert len(suivi) == 1
    assert (suivi[0].source_idx, suivi[0].status, suivi[0].id_cpro, suivi[0].line_id) == (
        "11_2025_dinum_1",
        "ligne_absente",
        "cpro-1",
        "",
    )


def test_match_ugap_enriches_existing_lines():
    factures = [silver_facture(numero="A1", id_cpro="cpro-1")]
    gold_lines = [gold_line(line_id="1", item_reference="Y1"), gold_line(line_id="2", item_reference="Y2")]
    ugap_lines = [silver_ugap_line(line_id=1, numero="A1", article="Y1")]

    lines, suivi = match_ugap(factures, gold_lines, ugap_lines)

    assert len(lines) == 2
    assert lines[0].fournisseur_in_fine_siren == "343059564"
    assert lines[1].fournisseur_in_fine_siren is None
    assert len(suivi) == 1
    assert (suivi[0].status, suivi[0].id_cpro, suivi[0].line_id) == ("matched", "cpro-1", "1")


def test_match_ugap_flags_ligne_absente():
    factures = [silver_facture(numero="A1", id_cpro="cpro-1")]
    gold_lines = [gold_line(line_id="1", item_reference="Y2")]
    ugap_lines = [silver_ugap_line(line_id=1, numero="A1", article="Y1")]

    lines, suivi = match_ugap(factures, gold_lines, ugap_lines)

    assert lines == gold_lines
    assert (suivi[0].status, suivi[0].id_cpro, suivi[0].line_id) == ("ligne_absente", "cpro-1", "")


def test_match_ugap_without_export_lines_keeps_gold_lines():
    factures = [silver_facture(numero="A1", id_cpro="cpro-1")]
    gold_lines = [gold_line(line_id="1"), gold_line(line_id="2")]

    lines, suivi = match_ugap(factures, gold_lines, [])

    assert lines == gold_lines
    assert suivi == []


def test_match_ugap_flags_facture_inconnue():
    factures = [silver_facture(numero="A1", id_cpro="cpro-1")]
    ugap_lines = [silver_ugap_line(line_id=1, numero="A9", article="Y9")]

    lines, suivi = match_ugap(factures, [], ugap_lines)

    assert lines == []
    assert len(suivi) == 1
    assert (suivi[0].numero_ugap, suivi[0].status, suivi[0].id_cpro) == ("A9", "facture_inconnue", None)


def test_match_ugap_ignores_non_ugap_factures():
    factures = [silver_facture(numero="A1", id_cpro="cpro-1", fournisseur_identifiant="123456789")]
    gold_lines = [gold_line(line_id="1", item_reference="Y1")]
    ugap_lines = [silver_ugap_line(line_id=1, numero="A1", article="Y1")]

    lines, suivi = match_ugap(factures, gold_lines, ugap_lines)

    assert lines == gold_lines
    assert lines[0].fournisseur_in_fine_siren is None
    assert [row.status for row in suivi] == ["facture_inconnue"]
