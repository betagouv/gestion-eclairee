# Fournisseur in fine des lignes facturées par une centrale d'achat

Statut : accepté

Une facture émise par une centrale d'achat (UGAP) porte la centrale comme
fournisseur dans Chorus Pro ; le fournisseur ayant réellement exécuté la ligne
(titulaire, constructeur) n'apparaît que dans les exports de factures de la
centrale. Le concept de **fournisseur in fine** est transverse aux centrales
d'achat, mais seule l'UGAP l'alimente aujourd'hui. Les champs sont ajoutés
uniquement sur les lignes gold, préfixés `fournisseur_in_fine_`, sans renommer
les champs `fournisseur_*` existants qui restent utiles en l'état. La centrale
est identifiée par le SIREN `776056467`.

Le rapprochement se fait en deux temps : la facture via
`numero == « Cde Client - N° »` (valeur toujours égale au `cbc:ID` du XML en
pratique), puis la ligne via `item_reference == « Article - N° »` dans le
périmètre de cette facture. Le bon de commande est retiré du rapprochement : une
facture n'a qu'un bon de commande, il n'apporte donc aucune discrimination au
niveau ligne, et il reste conservé en silver pour l'analyse. Une facture sans
aucune ligne gold reçoit des lignes créées depuis l'UGAP ; chaque ligne UGAP est
suivie dans une table unique (`gesec_facture_ugap_ligne`), avec les statuts
`matched`, `created`, `ligne_absente` ou `facture_inconnue`, sans création pour
les lignes non rattachées.

Le dédoublonnage des couples `(Cde Client - N°, Article - N°)` se fait en
silver, comme pour l'import CPRO : plusieurs fichiers peuvent contenir des
lignes communes. Ce sont des artefacts de facturation (paiements partiels,
re-commandes) et on garde la ligne à la date la plus récente
(« Date Paiement client », puis « Jour de création », tie-break par ordre
d'ingestion). Ce choix rend le rapprochement ligne déterministe : la règle
d'ambiguïté envisagée initialement a été supprimée. L'onglet DAE est exclu du
traitement : c'est un export similaire mais différent, dont les libellés de
colonnes divergent ; seul Dinum est importé pour l'instant.

Les chaînes de repli sont indépendantes pour la désignation
(`Titulaire 2` → `Constructeur` → `Code fournisseur` → NULL) et pour le SIREN
(`Siren Titulaire 2` → `SIREN Titulaire` → NULL). Les sentinelles `'-'`, `'#'`
et vide valent NULL. Les incohérences bloquantes (colonne ADV vide, montant
facturé HT absent, ratio de TVA indéterminé) lèvent une erreur explicite plutôt
que de produire une ligne silencieusement fausse.

## Options écartées

Renommer les champs `fournisseur_*` en `emetteur_*` : erreur de vocabulaire,
l'émetteur a déjà son bloc dédié dans Chorus Pro ; les valeurs actuelles du
fournisseur restent la référence côté CPRO. Dédoublonner en gold : la
détection de doublons entre fichiers est un travail de consolidation, fait au
même endroit que pour le CPRO. Rapprocher sur le bon de commande : sans
discrimination au niveau ligne. Rattacher malgré une ambiguïté : devenu inutile
avec le dédoublonnage. Porter les champs sur la facture : la ligne est l'unité
de rattachement, la facture est atteignable par `id_cpro`. Fusionner les
libellés Dinum et DAE en silver : c'est au gold de renommer et d'agréger.

## Conséquences

Le `cbc:ID` est extrait dans une table silver dédiée
(`silver_cpro_export_facture_xml_facture`) pour des checks de cohérence
ultérieurs, sans remontée au gold. Les exports UGAP doivent être déposés dans
`ugap/exports/` pour alimenter les champs, sinon ils restent NULL. Les lignes
créées depuis l'UGAP sont recalculées à chaque run, la table gold étant
reconstruite.
Quand une autre centrale d'achat sera intégrée, l'interface commune (format
d'entrée, résolveur, statuts) sera extraite à ce moment-là.
