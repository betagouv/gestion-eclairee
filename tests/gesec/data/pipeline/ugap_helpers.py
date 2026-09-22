import io
from typing import Any

import openpyxl

UGAP_HEADERS = [
    "Cde Client - N°",
    "Cde Client - N° cde chez le client",
    "Cde client - Jour de création",
    "Cde client - Date Paiement client",
    "Compte CRM DO - Univers BP",
    "Compte CRM - N° donneur d'ordre",
    "Ministère",
    "Part.: nom 1 organ.",
    "Part.: nom 2 organ.",
    "SIREN",
    "Inclus",
    "SAE Niveau 3",
    "SAE Niveau 4",
    "AC/SE (BP operateur état)",
    "Code GM",
    "Désignation GM",
    "Marché - N°",
    "Type d'offre Logiciels",
    "Article - Code Lot",
    "Désignation du Lot",
    "Article - Code fourniseur",
    "SIREN Titulaire",
    "BOA - Tête de groupe mondiale - Pays",
    "Type Entreprise: TPE/PME-PMI/ETI/Grande Entreprise",
    "Article - N°",
    "Constructeur (hardware ajout manuel)",
    "Titulaire 2 (Editeurs Multi Editeurs)",
    "Siren Titulaire 2",
    "Pays du Titualire 2",
    "Type ent Titulaire 2",
    "Sous Traitant (sur marchés Presta)",
    "Siren Ss Traitant",
    "Pays Ss Traitant",
    "Type ent Ss Traitant",
    "Article - N° (vue ADV)",
    "Texte ADV ligne 1",
    "Texte ADV ligne 2",
    "Texte ADV ligne 3",
    "Texte ADV ligne 4",
    "CE HT",
    "TVA Collectée",
    "CE TTC",
    "Qté commandées",
    "Montant Facturé HT",
]

UGAP_ROW = {
    "Cde Client - N°": 104521399,
    "Cde Client - N° cde chez le client": "E2024001253",
    "Cde client - Jour de création": "10/04/2025",
    "Cde client - Date Paiement client": "06/11/2025",
    "Compte CRM DO - Univers BP": "ETABLISSEMENTS PUBLICS",
    "Compte CRM - N° donneur d'ordre": 99082863,
    "Ministère": "M.CUL",
    "Part.: nom 1 organ.": "MUSEE ORSAY ET MUSEE ORANGERIE",
    "Part.: nom 2 organ.": "#",
    "SIREN": 180092447,
    "Inclus": "Oui",
    "SAE Niveau 3": "MUSEES ORSAY & MUSEE ORANGERIE",
    "SAE Niveau 4": "#",
    "AC/SE (BP operateur état)": "S/E",
    "Code GM": "33.01.04",
    "Désignation GM": "Services téléphonie fixe",
    "Marché - N°": 616024,
    "Type d'offre Logiciels": "-",
    "Article - Code Lot": "19U103/001",
    "Désignation du Lot": "Services de téléphonie fixe ainsi que les prestations associées",
    "Article - Code fourniseur": "SOC FRANCAISE DU RADIOTELEPHONE - S",
    "SIREN Titulaire": 343059564,
    "BOA - Tête de groupe mondiale - Pays": "LUXEMBOURG",
    "Type Entreprise: TPE/PME-PMI/ETI/Grande Entreprise": "Grande Entreprise",
    "Article - N°": 5650607,
    "Constructeur (hardware ajout manuel)": "-",
    "Titulaire 2 (Editeurs Multi Editeurs)": "-",
    "Siren Titulaire 2": "-",
    "Pays du Titualire 2": "-",
    "Type ent Titulaire 2": "-",
    "Sous Traitant (sur marchés Presta)": "-",
    "Siren Ss Traitant": "-",
    "Pays Ss Traitant": "-",
    "Type ent Ss Traitant": "-",
    "Article - N° (vue ADV)": "Indonésie - Fixe",
    "Texte ADV ligne 1": "Indonésie - Fixe",
    "Texte ADV ligne 2": "par 1000 minutes",
    "Texte ADV ligne 3": "Reste Asie et Océanie",
    "Texte ADV ligne 4": "Communications fixes sortantes - accès direct",
    "CE HT": 5.94,
    "TVA Collectée": 1.19,
    "CE TTC": 7.13,
    "Qté commandées": 1.0,
    "Montant Facturé HT": 5.94,
}


def ugap_row(**overrides: Any) -> dict[str, Any]:
    row = dict(UGAP_ROW)
    row.update(overrides)
    return row


def build_xlsx(sheets: dict[str, list[list]], banner: bool = True) -> bytes:
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        worksheet = workbook.create_sheet(title)
        if banner:
            worksheet.append([None] * len(rows[0]))
        for row in rows:
            worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_ugap_xlsx(sheets: dict[str, list[dict]], banner: bool = True) -> bytes:
    matrices = {
        title: [UGAP_HEADERS] + [[row.get(header) for header in UGAP_HEADERS] for row in rows]
        for title, rows in sheets.items()
    }
    return build_xlsx(matrices, banner=banner)
