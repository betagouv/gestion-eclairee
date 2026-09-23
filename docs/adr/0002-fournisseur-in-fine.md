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

Le rapprochement se fait en deux temps : les factures UGAP sont rattachées à
leur commande par `cac:Delivery/cbc:ID` de la facture XML (partie avant `-`,
« commande-donneur d'ordre », normalisée), comparée à « Cde Client - N° »
normalisée ; puis chaque ligne l'est par article normalisé. Le `cbc:ID` du XML
est le numéro de facture, pas le numéro de commande : l'égalité supposée
initialement `numero == « Cde Client - N° »` était erronée, jamais mesurée, et
la production était intégralement `facture_inconnue`. L'enrichissement
`fournisseur_in_fine_*` couvre toutes les lignes gold `(commande, article)` des
factures d'une commande, y compris les commandes multi-factures (3 194
mesurées). Chaque correspondance `(ligne UGAP, ligne gold)` produit une ligne de
suivi dans `gesec_facture_ugap_ligne`, avec les statuts `matched`,
`ligne_absente` ou `facture_inconnue` ; le statut `created` est supprimé (0 cas
atteignable, risque de double compte), aucune ligne gold n'est créée depuis
l'export.

Le dédoublonnage des lignes d'export se fait en silver, comme pour l'import
CPRO : plusieurs fichiers peuvent contenir des lignes communes. La clé est
`(commande, article, date de paiement, montant HT)` et la dernière ligne triée
par `(source, source_idx)` gagne ; les 218 lignes auparavant écartées sont des
paiements partiels réels, désormais conservés. L'onglet DAE est exclu du
traitement : c'est un export similaire mais différent, dont les libellés de
colonnes divergent ; seul Dinum est importé pour l'instant.

Les factures XML en ancien format (`UBL-Invoice-01.01.01`) n'ont ni identifiant
standard ni note : un `cbc:Name` entièrement numérique devient le numéro
d'article, `item_name` prenant la 1re ligne de `cbc:Description`. La note
« Référence UGAP » est extraite en silver (`reference_ugap`) pour contrôle mais
n'est pas consommée par le gold : sa couverture (1 937 commandes) est un
sous-ensemble de celle de `cac:Delivery` (1 940), elle est absente de l'ancien
format et diverge sur 4 factures.

Les chaînes de repli sont indépendantes pour la désignation
(`Titulaire 2` → `Constructeur` → `Code fournisseur` → NULL) et pour le SIREN
(`Siren Titulaire 2` → `SIREN Titulaire` → NULL). Les sentinelles `'-'`, `'#'`
et vide valent NULL. Les lignes d'export invalides sont rejetées en silver et
tracées avec le statut `Validation error`.

## Options écartées

Rapprocher sur le numéro de facture : hypothèse initiale erronée, le `cbc:ID`
du XML est le numéro de facture et ne recoupe jamais les numéros de commande.
Rapprocher sur la note « Référence UGAP » seule : absente de l'ancien format,
4 divergences, couverture incluse dans celle de `cac:Delivery` ; elle n'est
extraite que pour contrôle. Rapprocher sur le bon de commande : niveau EJ,
+72 lignes mesurées, rattachements croisés possibles ; il reste conservé en
silver pour l'analyse. Rapprocher sur l'article seul : une référence d'article
n'identifie pas la commande. Créer des lignes gold depuis l'export : le statut
`created` n'est jamais atteint et exposerait les commandes multi-factures au
double compte. Dédoublonner `(commande, article)` : écarterait des paiements
partiels réels. Filtrer le rapprochement sur l'univers « ministères » : les
commandes sans facture CPRO restent suivies en `facture_inconnue`, le périmètre
relève du téléchargement. Renommer les champs `fournisseur_*` en `emetteur_*` :
erreur de vocabulaire, l'émetteur a déjà son bloc dédié dans Chorus Pro ; les
valeurs actuelles du fournisseur restent la référence côté CPRO. Dédoublonner en
gold : la détection de doublons entre fichiers est un travail de consolidation,
fait au même endroit que pour le CPRO. Porter les champs sur la facture : la
ligne est l'unité de rattachement, la facture est atteignable par `id_cpro`.
Fusionner les libellés Dinum et DAE en silver : c'est au gold de renommer et
d'agréger.

## Conséquences

Les 12 691 lignes `facture_inconnue` relèvent du périmètre de téléchargement :
4 962 commandes de l'export sans facture CPRO (ODA/BUDAT, ministères absents),
à élargir dans un autre chantier. Les valeurs de fournisseur reflètent le
référentiel à la date d'extraction (éditeurs renommés ou rachetés) et la colonne
Constructeur, saisie manuellement, porte ~3 % d'erreurs manifestes. L'onglet DAE
et la lecture factur-x ne sont pas couverts (18 factures UGAP sans XML). Un
conflit de fournisseur pour un même couple est résolu par la dernière ligne
triée gagnante, sans trace. 348 lignes dont la facture est déposée après la date
de paiement référencent la ligne gold. Le numéro de facture (`cbc:ID`), le
`delivery_id` et la référence UGAP sont extraits dans une table silver dédiée
(`silver_cpro_export_facture_xml_facture`) ; seul `delivery_id` sert au gold,
les autres restent pour les checks de cohérence. Les exports UGAP doivent être
déposés dans `ugap/exports/` pour alimenter les champs, sinon ils restent NULL.
L'enrichissement est recalculé à chaque run, la table gold étant reconstruite.
Quand une autre centrale d'achat sera intégrée, l'interface commune (format
d'entrée, résolveur, statuts) sera extraite à ce moment-là.
