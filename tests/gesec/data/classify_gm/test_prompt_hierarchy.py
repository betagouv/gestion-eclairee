from decimal import Decimal
from typing import Any

from gesec.data.classify_gm.prompt_hierarchy import (
    build_domain_user_prompt,
    build_leaf_user_prompt,
    build_segment_user_prompt,
)


def test_prompts_include_objet_facture():
    lignes: list[dict[str, Any]] = []
    fournisseur = "Fournisseur"
    objet = "DGAFP - ASI pilotage"
    mt_ttc = Decimal("120")

    domain_prompt = build_domain_user_prompt(
        fournisseur_designation=fournisseur,
        objet_facture=objet,
        mt_ttc=mt_ttc,
        lignes=lignes,
        domains=[],
    )
    segment_prompt = build_segment_user_prompt(
        fournisseur_designation=fournisseur,
        objet_facture=objet,
        mt_ttc=mt_ttc,
        lignes=lignes,
        domain="33",
        domain_libelle="Informatique",
        segments=[],
    )
    leaf_prompt = build_leaf_user_prompt(
        fournisseur_designation=fournisseur,
        objet_facture=objet,
        mt_ttc=mt_ttc,
        lignes=lignes,
        domain="33",
        domain_libelle="Informatique",
        segment="33.02",
        segment_libelle="Logiciels",
        leaves=[],
    )

    assert "Objet Facture: DGAFP - ASI pilotage" in domain_prompt
    assert "Objet Facture: DGAFP - ASI pilotage" in segment_prompt
    assert "Objet Facture: DGAFP - ASI pilotage" in leaf_prompt
