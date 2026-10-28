"""Prompts de classification GM hiérarchique (domaine → segment → feuille)."""

from __future__ import annotations

from typing import Any

from gesec.data.classify_gm.prompt import parse_llm_content  # noqa: F401 — re-export
from gesec.data.classify_gm.referential import (
    NON_CLASSIFIE,
    GmEntry,
    HierarchyNode,
    domain_libelle_map,
    segment_libelle_map,
)

RULES_SHORT = """\
Règles (prioritaires) :
1. Objet dominant = ligne(s) au plus gros montant TTC (ignore annexes faibles).
2. Licence / souscription éditeur / Maintenance → logiciels (33.02) ; MCO/TMA/maintenance \
applicative / hébergement applicatif → prestations SI (33.04).
3. Mission SI / intégrateur / ESN → 33.xx ; conseil métier hors SI → 40.xx.
4. Opérateur téléphonie / abonnement → 33.01 ; LAN/WAN/SFP/switch → 33.05.
5. Fournitures bureau / papier / stylos → 41.xx (moyens généraux), pas 33.
6. « Non classifié » en dernier recours seulement.
"""

SYSTEM_PROMPT_HIERARCHY = f"""\
Tu es un expert de la nomenclature Groupe Marchandise (GM) de l'État français.
Tu classifies une facture par étapes (domaine, puis segment, puis code feuille).
Tu réponds uniquement avec le JSON demandé. Le code choisi doit être EXACTEMENT \
l'un des codes de la liste fournie, ou "{NON_CLASSIFIE}".
Chaque option affiche le chemin de libellés depuis la racine (ex. \
« Informatique et télécoms + Logiciels + Antivirus »).
Le contexte de domaine décrit le périmètre et les frontières avec les domaines voisins : \
utilise-le pour aiguiller correctement.

{RULES_SHORT}
"""


def _facture_block(
    *,
    fournisseur_designation: str | None,
    objet_facture: str | None,
    mt_ttc: Any,
    lignes: list[dict[str, Any]],
) -> str:
    lignes_block = []
    for ligne in lignes:
        amount = ligne.get("line_amount_incl_tax")
        amount_str = "" if amount is None else str(amount)
        lignes_block.append(
            "\n".join(
                [
                    f"  - Line ID: {ligne.get('line_id') or ''}",
                    f"    Item Name: {ligne.get('item_name') or ''}",
                    f"    Item Description: {ligne.get('item_description') or ''}",
                    f"    Line Amount Incl Tax: {amount_str}",
                ]
            )
        )
    lignes_text = "\n".join(lignes_block) if lignes_block else "  (aucune ligne)"
    return f"""\
Fournisseur Designation: {fournisseur_designation or ""}
Objet Facture: {objet_facture or ""}
Mt Ttc: {mt_ttc if mt_ttc is not None else ""}

Lignes d'articles:
{lignes_text}
"""


def _domain_context_block(domain: str, domain_libelle: str, domain_contexte: str | None) -> str:
    ctx = (domain_contexte or "").strip()
    if not ctx:
        return ""
    return f"Contexte du domaine {domain} ({domain_libelle}) :\n{ctx}\n"


def _format_chosen_path(codes_and_labels: list[tuple[str, str]]) -> str:
    """Ex. 33 (Informatique…) + 33.02 (Logiciels)."""
    parts = [f"{code} ({label})" if label else code for code, label in codes_and_labels]
    return " + ".join(parts)


def build_domain_user_prompt(
    *,
    fournisseur_designation: str | None,
    objet_facture: str | None,
    mt_ttc: Any,
    lignes: list[dict[str, Any]],
    domains: list[HierarchyNode],
) -> str:
    # Étape 1 : libellé domaine + contexte enrichi (périmètre / frontières)
    options = "\n".join(d.as_prompt_line(path_libelles=[d.libelle]) for d in domains)
    options += f"\n- {NON_CLASSIFIE} | Aucun domaine ne convient"
    return f"""\
Étape 1/3 — Choisis le DOMAINE GM (préfixe, ex. 33, 41) pour cette facture.
Chaque option est : code | libellé du domaine : contexte (périmètre et frontières).

{
        _facture_block(
            fournisseur_designation=fournisseur_designation,
            objet_facture=objet_facture,
            mt_ttc=mt_ttc,
            lignes=lignes,
        )
    }
Domaines autorisés:
{options}

Consignes: un seul code domaine de la liste ; appuie-toi sur le contexte ; justifie brièvement.
"""


def build_segment_user_prompt(
    *,
    fournisseur_designation: str | None,
    objet_facture: str | None,
    mt_ttc: Any,
    lignes: list[dict[str, Any]],
    domain: str,
    domain_libelle: str,
    segments: list[HierarchyNode],
    domain_contexte: str | None = None,
) -> str:
    # Étape 2 : libellé domaine + segment (+ rappel contexte domaine)
    options = "\n".join(s.as_prompt_line(path_libelles=[domain_libelle, s.libelle]) for s in segments)
    options += f"\n- {NON_CLASSIFIE} | Aucun segment ne convient"
    chosen = _format_chosen_path([(domain, domain_libelle)])
    ctx_block = _domain_context_block(domain, domain_libelle, domain_contexte)
    return f"""\
Étape 2/3 — Chemin déjà choisi: {chosen}.
Choisis le SEGMENT GM (ex. 33.02, 33.04) pour cette facture.
Chaque option est : code | libellé domaine + libellé segment.
{ctx_block}
{
        _facture_block(
            fournisseur_designation=fournisseur_designation,
            objet_facture=objet_facture,
            mt_ttc=mt_ttc,
            lignes=lignes,
        )
    }
Segments autorisés (sous {chosen}):
{options}

Consignes: un seul code segment de la liste ; reste cohérent avec le contexte du domaine ; justifie brièvement.
"""


def build_leaf_user_prompt(
    *,
    fournisseur_designation: str | None,
    objet_facture: str | None,
    mt_ttc: Any,
    lignes: list[dict[str, Any]],
    domain: str,
    domain_libelle: str,
    segment: str,
    segment_libelle: str,
    leaves: list[GmEntry],
    domain_contexte: str | None = None,
) -> str:
    # Étape 3 : libellé domaine + segment + feuille (+ rappel contexte domaine)
    options_lines = []
    for e in leaves:
        path = [domain_libelle, segment_libelle, e.libelle or e.code]
        path_str = " + ".join(x for x in path if x)
        desc = (e.description or "").strip()
        if desc:
            options_lines.append(f"- {e.code} | {path_str} : {desc}")
        else:
            options_lines.append(f"- {e.code} | {path_str}")
    options = "\n".join(options_lines)
    options += f"\n- {NON_CLASSIFIE} | Aucun code feuille ne convient"
    chosen = _format_chosen_path([(domain, domain_libelle), (segment, segment_libelle)])
    ctx_block = _domain_context_block(domain, domain_libelle, domain_contexte)
    return f"""\
Étape 3/3 — Chemin déjà choisi: {chosen}.
Choisis le code GM FEUILLE le plus précis pour cette facture.
Chaque option est : code | libellé domaine + libellé segment + libellé feuille.
{ctx_block}
{
        _facture_block(
            fournisseur_designation=fournisseur_designation,
            objet_facture=objet_facture,
            mt_ttc=mt_ttc,
            lignes=lignes,
        )
    }
Codes GM autorisés (sous {chosen}):
{options}

Consignes: un seul code de la liste ; justifie brièvement (objet dominant + règle).
"""


def response_format_choice(field: str, allowed_codes: list[str]) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": f"GmHierarchy_{field}",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    field: {"type": "string", "enum": allowed_codes},
                    "raison": {"type": "string"},
                },
                "required": [field, "raison"],
            },
        },
    }


def build_label_maps(entries: list[GmEntry]) -> tuple[dict[str, str], dict[str, str]]:
    """Convenience for classify_hierarchy."""
    return domain_libelle_map(entries), segment_libelle_map(entries)
