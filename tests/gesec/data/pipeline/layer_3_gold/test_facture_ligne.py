from datetime import date
from decimal import Decimal
from typing import Any, Optional

from gesec.data.pipeline.layer_2_silver.schemas import (
    SilverCproExportFacture,
    SilverCproExportFactureXmlFacture,
    SilverUgapExportFacture,
)
from gesec.data.pipeline.layer_3_gold.constants import UGAP_SIREN
from gesec.data.pipeline.layer_3_gold.facture_ligne import (
    build_ugap_ligne,
    extract_numero_commande_ugap,
    is_ugap_facture,
    match_ugap,
    normalize_reference,
    resolve_fournisseur_in_fine,
)
from gesec.data.pipeline.layer_3_gold.schemas import GoldCproExportFactureLigne


def silver_facture(
    numero: str = "900000002",
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


def silver_facture_xml(
    id_cpro: str = "cpro-1",
    delivery_id: Optional[str] = "0900000001-0080000002",
) -> SilverCproExportFactureXmlFacture:
    return SilverCproExportFactureXmlFacture(
        id_cpro=id_cpro,
        xml_schema="UBL-Invoice-2",
        numero="700123456789",
        delivery_id=delivery_id,
    )


def silver_ugap_line(
    line_id: int = 1,
    numero: str = "900000001",
    article: str = "7000001",
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
        compte_crm_numero_donneur_d_ordre="80000002",
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
    line_id: str = "00010",
    item_reference: str = "7000001",
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


def test_extract_numero_commande_ugap():
    assert extract_numero_commande_ugap(None) is None
    assert extract_numero_commande_ugap("") is None
    assert extract_numero_commande_ugap("abc") is None
    assert extract_numero_commande_ugap("0900000001-0080000002") == "900000001"
    assert extract_numero_commande_ugap("900000001-80000002") == "900000001"


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
    assert suivi.numero_commande_ugap == "A9"
    assert suivi.line_id == ""
    assert suivi.article_numero == "Y9"
    assert suivi.status == "ligne_absente"
    assert suivi.status_details is None

    suivi = build_ugap_ligne(line, "matched", id_cpro="cpro-1", line_id="00010")

    assert suivi.line_id == "00010"
    assert suivi.status == "matched"


def test_match_ugap_requires_xml_metadata():
    factures = [silver_facture(numero="900000001", id_cpro="cpro-1")]
    gold_lines = [gold_line(id_cpro="cpro-1", line_id="00010", item_reference="7000001")]
    ugap_lines = [silver_ugap_line(numero="900000001", article="7000001")]

    lines, suivi = match_ugap(factures, [], gold_lines, ugap_lines)

    assert lines == gold_lines
    assert lines[0].fournisseur_in_fine_siren is None
    assert [(row.status, row.id_cpro) for row in suivi] == [("facture_inconnue", None)]


def test_match_ugap_enriches_matched_gold_line():
    factures = [silver_facture(numero="900000002", id_cpro="cpro-1")]
    xml_factures = [silver_facture_xml(id_cpro="cpro-1")]
    gold_lines = [gold_line(id_cpro="cpro-1", line_id="00010", item_reference="7000001")]
    ugap_lines = [silver_ugap_line(numero="900000001", article="7000001")]

    lines, suivi = match_ugap(factures, xml_factures, gold_lines, ugap_lines)

    assert len(lines) == 1
    assert lines[0].fournisseur_in_fine_designation == "FOURNISSEUR"
    assert lines[0].fournisseur_in_fine_siren == "343059564"
    assert len(suivi) == 1
    assert (suivi[0].numero_commande_ugap, suivi[0].status, suivi[0].id_cpro, suivi[0].line_id) == (
        "900000001",
        "matched",
        "cpro-1",
        "00010",
    )


def test_match_ugap_normalizes_references():
    factures = [silver_facture(numero="900000002", id_cpro="cpro-1")]
    xml_factures = [silver_facture_xml(id_cpro="cpro-1")]
    gold_lines = [gold_line(id_cpro="cpro-1", line_id="00010", item_reference="000000000007000001")]
    ugap_lines = [silver_ugap_line(numero="00900000001", article="0007000001")]

    lines, suivi = match_ugap(factures, xml_factures, gold_lines, ugap_lines)

    assert lines[0].fournisseur_in_fine_siren == "343059564"
    assert [row.status for row in suivi] == ["matched"]


def test_match_ugap_enriches_all_commande_factures():
    factures = [
        silver_facture(numero="900000003", id_cpro="cpro-b"),
        silver_facture(numero="900000002", id_cpro="cpro-a"),
    ]
    xml_factures = [silver_facture_xml(id_cpro="cpro-b"), silver_facture_xml(id_cpro="cpro-a")]
    gold_lines = [
        gold_line(id_cpro="cpro-b", line_id="00010", item_reference="7000001"),
        gold_line(id_cpro="cpro-a", line_id="00010", item_reference="7000001"),
    ]
    ugap_lines = [silver_ugap_line(numero="900000001", article="7000001")]

    lines, suivi = match_ugap(factures, xml_factures, gold_lines, ugap_lines)

    assert [line.fournisseur_in_fine_siren for line in lines] == ["343059564", "343059564"]
    assert [(row.status, row.id_cpro, row.line_id) for row in suivi] == [
        ("matched", "cpro-a", "00010"),
        ("matched", "cpro-b", "00010"),
    ]


def test_match_ugap_flags_ligne_absente():
    factures = [
        silver_facture(numero="900000003", id_cpro="cpro-b"),
        silver_facture(numero="900000002", id_cpro="cpro-a"),
    ]
    xml_factures = [silver_facture_xml(id_cpro="cpro-b"), silver_facture_xml(id_cpro="cpro-a")]
    gold_lines = [
        gold_line(id_cpro="cpro-a", line_id="00010", item_reference="9999999"),
        gold_line(id_cpro="cpro-b", line_id="00010", item_reference="8888888"),
    ]
    ugap_lines = [silver_ugap_line(numero="900000001", article="7000001")]

    lines, suivi = match_ugap(factures, xml_factures, gold_lines, ugap_lines)

    assert lines == gold_lines
    assert len(suivi) == 1
    assert (suivi[0].status, suivi[0].id_cpro, suivi[0].line_id, suivi[0].status_details) == (
        "ligne_absente",
        "cpro-a",
        "",
        "article absent des 2 factures de la commande",
    )


def test_match_ugap_flags_facture_inconnue():
    factures = [silver_facture(numero="900000002", id_cpro="cpro-1")]
    xml_factures = [silver_facture_xml(id_cpro="cpro-1")]
    ugap_lines = [silver_ugap_line(numero="999999999", article="7000001")]

    lines, suivi = match_ugap(factures, xml_factures, [], ugap_lines)

    assert lines == []
    assert len(suivi) == 1
    assert (suivi[0].numero_commande_ugap, suivi[0].status, suivi[0].id_cpro) == (
        "999999999",
        "facture_inconnue",
        None,
    )


def test_match_ugap_ignores_non_ugap_factures():
    factures = [silver_facture(numero="900000001", id_cpro="cpro-1", fournisseur_identifiant="123456789")]
    xml_factures = [silver_facture_xml(id_cpro="cpro-1")]
    gold_lines = [gold_line(id_cpro="cpro-1", line_id="00010", item_reference="7000001")]
    ugap_lines = [silver_ugap_line(numero="900000001", article="7000001")]

    lines, suivi = match_ugap(factures, xml_factures, gold_lines, ugap_lines)

    assert lines == gold_lines
    assert lines[0].fournisseur_in_fine_siren is None
    assert [row.status for row in suivi] == ["facture_inconnue"]


def test_match_ugap_ignores_invalid_delivery_id():
    factures = [silver_facture(numero="900000002", id_cpro="cpro-1")]
    xml_factures = [
        silver_facture_xml(id_cpro="cpro-1", delivery_id=None),
        silver_facture_xml(id_cpro="cpro-1", delivery_id="abc"),
    ]
    gold_lines = [gold_line(id_cpro="cpro-1", line_id="00010", item_reference="7000001")]
    ugap_lines = [silver_ugap_line(numero="900000001", article="7000001")]

    lines, suivi = match_ugap(factures, xml_factures, gold_lines, ugap_lines)

    assert lines == gold_lines
    assert lines[0].fournisseur_in_fine_siren is None
    assert [row.status for row in suivi] == ["facture_inconnue"]


def test_match_ugap_preserves_gold_line_order():
    factures = [silver_facture(numero="900000002", id_cpro="cpro-1")]
    xml_factures = [silver_facture_xml(id_cpro="cpro-1")]
    gold_lines = [
        gold_line(id_cpro="cpro-1", line_id="00010", item_reference="1111111"),
        gold_line(id_cpro="cpro-1", line_id="00020", item_reference="7000001"),
        gold_line(id_cpro="cpro-1", line_id="00030", item_reference="2222222"),
    ]
    ugap_lines = [silver_ugap_line(numero="900000001", article="7000001")]

    lines, suivi = match_ugap(factures, xml_factures, gold_lines, ugap_lines)

    assert [line.line_id for line in lines] == ["00010", "00020", "00030"]
    assert [line.fournisseur_in_fine_siren for line in lines] == [None, "343059564", None]
    assert [(row.status, row.line_id) for row in suivi] == [("matched", "00020")]


def test_match_ugap_conflicting_suppliers_last_sorted_wins():
    factures = [silver_facture(numero="900000002", id_cpro="cpro-1")]
    xml_factures = [silver_facture_xml(id_cpro="cpro-1")]
    gold_lines = [gold_line(id_cpro="cpro-1", line_id="00010", item_reference="7000001")]
    ugap_lines = [
        silver_ugap_line(
            source="ugap/b.xlsx",
            source_idx="1",
            numero="900000001",
            article="7000001",
            article_code_fourniseur="B",
            siren_titulaire="222222222",
        ),
        silver_ugap_line(
            source="ugap/a.xlsx",
            source_idx="2",
            numero="900000001",
            article="7000001",
            article_code_fourniseur="A",
            siren_titulaire="111111111",
        ),
    ]

    lines, suivi = match_ugap(factures, xml_factures, gold_lines, ugap_lines)

    assert lines[0].fournisseur_in_fine_designation == "B"
    assert lines[0].fournisseur_in_fine_siren == "222222222"
    assert [(row.status, row.source) for row in suivi] == [("matched", "ugap/a.xlsx"), ("matched", "ugap/b.xlsx")]


def test_match_ugap_without_export_lines_keeps_gold_lines():
    factures = [silver_facture(numero="900000002", id_cpro="cpro-1")]
    xml_factures = [silver_facture_xml(id_cpro="cpro-1")]
    gold_lines = [gold_line(id_cpro="cpro-1"), gold_line(id_cpro="cpro-1", line_id="00020")]

    lines, suivi = match_ugap(factures, xml_factures, gold_lines, [])

    assert lines == gold_lines
    assert suivi == []
