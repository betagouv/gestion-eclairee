"""Prompts et schéma JSON pour l'extraction des lignes de facture."""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT_EXTRACTION = """\
Tu extrais l'en-tête et les lignes de facture d'un document PDF non structuré (scan ou PDF natif).
Chaque ligne correspond à un article ou une prestation facturée (pas les totaux TVA globaux \
ni les mentions légales seules).
Inclus les postes du tableau de facturation même à 0,00 € (prestations offertes, gratuités, \
remises à zéro) lorsqu'ils sont listés comme lignes métier. Exclure seulement les totaux \
globaux, TVA récapitulative et mentions légales, pas les lignes à montant nul explicite.
objet_facture : objet ou intitulé de la facture tel qu'il apparaît dans l'en-tête (champ \
« Objet », titre du devis/facture, libellé de mission, référence de prestation globale, etc.). \
Ne complète ni n'interprète au-delà du texte du document : si aucun objet explicite n'est \
identifiable, mets null.
Tu réponds uniquement avec le JSON demandé. Les montants sont des nombres décimaux \
(séparateur point). Devise par défaut EUR si absente.
line_id : identifiant ou numéro de ligne dans la facture ; sinon numérote "1", "2", … \
dans l'ordre d'apparition.
"""

_LIGNE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "line_id": {"type": "string"},
        "item_name": {"type": "string"},
        "item_description": {"type": "string"},
        "item_reference": {"type": ["string", "null"]},
        "quantity": {"type": ["number", "null"]},
        "quantity_unit_code": {"type": "string"},
        "unit_price": {"type": ["number", "null"]},
        "line_amount_excl_tax": {"type": ["number", "null"]},
        "line_amount_incl_tax": {"type": ["number", "null"]},
        "line_amount_vat": {"type": ["number", "null"]},
        "currency": {"type": "string"},
    },
    "required": [
        "line_id",
        "item_name",
        "item_description",
        "item_reference",
        "quantity",
        "quantity_unit_code",
        "unit_price",
        "line_amount_excl_tax",
        "line_amount_incl_tax",
        "line_amount_vat",
        "currency",
    ],
}


def response_format_lignes() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "FactureLignesExtraction",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "objet_facture": {"type": ["string", "null"]},
                    "lignes": {
                        "type": "array",
                        "items": _LIGNE_SCHEMA,
                    },
                },
                "required": ["objet_facture", "lignes"],
            },
        },
    }


def build_text_user_prompt(*, id_cpro: str, content: str, content_kind: str) -> str:
    return (
        f"Identifiant Chorus Pro (id_cpro) : {id_cpro}\n"
        "Extrais objet_facture (en-tête, texte explicite uniquement) et les lignes de facturation "
        "(y compris postes à 0,00 €).\n"
        f"Contenu ({content_kind}) :\n\n{content}"
    )
