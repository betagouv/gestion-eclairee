import io
from typing import Any

import openpyxl

UGAP_HEADERS = [
    "Numéro de commande UGAP",
    "Numéro de commande chez le client",
    "N° facture",
    "Jour de création de la commande UGAP",
    "Jour de paiement de la commande UGAP",
    "Univers clients UGAP",
    "Code du Donneur d'ordre",
    "Ministe de rattachement et ou tutelle",
    "Part.: nom 1 organ.",
    "Part.: nom 2 organ.",
    "SIREN",
    "SAE Niveau 3",
    "SAE Niveau 4",
    "AC/SE (BP operateur état)",
    "Code GM",
    "Désignation du GM",
    "Marché - N°",
    "Type offre logicielle",
    "Code Lot",
    "Désignation du Lot",
    "Désignation du Titualire de marché",
    "Pays Titulaire 1",
    "Type Entreprise Titulaire 1",
    "Siren Titultaire 1",
    "Code Article UGAP",
    "Constructeur de l'article",
    "Titulaire de rang 2 (Marche Multi Editeurs)",
    "Pays Titulaire 2",
    "Siren Titulaire 2",
    "Type ent Titulaire 2",
    "Sous Traitant (sur marchés Presta)",
    "Pays Ss Traitant",
    "Siren Ss Traitant",
    "Type ent Ss Traitant",
    "Article - N° (vue ADV)",
    "Texte ADV ligne 1",
    "Texte ADV ligne 2",
    "Texte ADV ligne 3",
    "Texte ADV ligne 4",
    "CE HT",
    "TVA",
    "CE TTC",
    "Qté Article commandée",
    "Montant Facturé HT",
]

UGAP_ROW = {
    "Numéro de commande UGAP": 103858990,
    "Numéro de commande chez le client": 1000414071,
    "N° facture": 7004133026,
    "Jour de création de la commande UGAP": "12/12/2023",
    "Jour de paiement de la commande UGAP": "01/01/2025",
    "Univers clients UGAP": "CAISSES ET ENTREPRISES",
    "Code du Donneur d'ordre": 75900029,
    "Ministe de rattachement et ou tutelle": "Non affecté",
    "Part.: nom 1 organ.": "CNAV",
    "Part.: nom 2 organ.": "#",
    "SIREN": 180035032,
    "SAE Niveau 3": "#",
    "SAE Niveau 4": "#",
    "AC/SE (BP operateur état)": "#",
    "Code GM": "33.02.11",
    "Désignation du GM": "Logiciels pour l'environnement de travai",
    "Marché - N°": 617409,
    "Type offre logicielle": "Multi Editeurs",
    "Code Lot": "19U045/001",
    "Désignation du Lot": "Commercialisation et animation d'une bibliothèque multi-édit",
    "Désignation du Titualire de marché": "SCC FRANCE",
    "Pays Titulaire 1": "UNITED KINGDOM",
    "Type Entreprise Titulaire 1": "Grande Entreprise",
    "Siren Titultaire 1": 424982650,
    "Code Article UGAP": 899637,
    "Constructeur de l'article": "HP",
    "Titulaire de rang 2 (Marche Multi Editeurs)": "CITRIX SYSTEMES FRANCE",
    "Pays Titulaire 2": "FRANCE",
    "Siren Titulaire 2": "PME",
    "Type ent Titulaire 2": 410117303,
    "Sous Traitant (sur marchés Presta)": "#N/A",
    "Pays Ss Traitant": "#N/A",
    "Siren Ss Traitant": "#N/A",
    "Type ent Ss Traitant": "#N/A",
    "Article - N° (vue ADV)": "Souscription - Editeur 14984",
    "Texte ADV ligne 1": "Souscription - Editeur 14984",
    "Texte ADV ligne 2": "Windows 11 Pro",
    "Texte ADV ligne 3": "lors de la reprise du PC réformé ou de l'intervention",
    "Texte ADV ligne 4": "Livré avec clavier et souris",
    "CE HT": 5.94,
    "TVA": 1.19,
    "CE TTC": 7.13,
    "Qté Article commandée": 1.0,
    "Montant Facturé HT": 5.94,
}


def ugap_row(**overrides: Any) -> dict[str, Any]:
    row = dict(UGAP_ROW)
    row.update(overrides)
    return row


def build_xlsx(sheets: dict[str, list[list]]) -> bytes:
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        worksheet = workbook.create_sheet(title)
        for row in rows:
            worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_ugap_xlsx(sheets: dict[str, list[dict]]) -> bytes:
    matrices = {
        title: [UGAP_HEADERS] + [[row.get(header) for header in UGAP_HEADERS] for row in rows]
        for title, rows in sheets.items()
    }
    return build_xlsx(matrices)
