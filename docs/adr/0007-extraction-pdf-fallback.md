# Extraction des factures PDF sans pivot XML

Statut : accepté

Certaines factures Chorus Pro ne fournissent aucun pivot XML exploitable, y
compris sous forme de Factur-X. Le gold restait alors sans lignes, et donc sans
objet ni classement GM, alors que la version PDF de la facture était disponible
dans l'archive téléchargée. Le pipeline ajoute donc un fallback : lire le PDF,
en extraire un Markdown, demander les lignes et l'objet au LLM, puis alimenter
le gold uniquement pour les factures que le chemin XML n'a pas couvertes.

## Périmètre

Une facture est candidate au fallback si son archive ne contient aucun `.xml`
sous `pivot/`, y compris un `*.factur-x.xml`. Les autres pièces jointes ne sont
pas des sources de lignes. L'en-tête de la facture doit exister dans
`gesec_facture` : sans lui, l'extraction est inutile et le statut
`header_missing` est enregistré sans appel OCR ni LLM.

Un seul PDF est retenu par facture : la première pièce jointe de catégorie
`FACTURE_PDF` dans l'ordre du pivot, avec le suffixe `.i` des doublons reconstruit
comme pour les pivots XML. Les PDF dépassant la limite de pages configurée sont
marqués `too_large` sans OCR.

## Persistance bronze

Les tentatives sont stockées dans `bronze_extract_pdf`, une ligne par
`id_cpro` avec le JSON brut du LLM, les empreintes PDF/Markdown, les chemins S3,
le statut, l'erreur et un compteur `attempts`. Cette table permet de reprendre
un run sans refaire OCR ni LLM, de distinguer les erreurs réessayables des
échecs définitifs, et de conserver la trace de l'extraction qui a alimenté le
gold. Elle est créée à la volée, comme les autres tables de travail, et non par
une migration Django.

Le Markdown OCR est mis en cache dans
`cpro/extract_pdf/facture_{id_cpro}/{nom_pdf}.md` ; `reprocess` et `--force-ocr`
le recalculent. Le PDF n'est jamais copié dans le dépôt.

Les statuts sont `success`, `no_lines`, `failed`, `header_missing`, `no_pdf` et
`too_large`. Les modes de la commande distinguent les factures jamais tentées
(`new`), les erreurs existantes (`retry`, filtrable par `--error-type`), et les
lignes déjà présentes (`reprocess`).

## Silver et gold

Le bronze est transformé en deux tables silver : facture et ligne. Le silver ne
dépend pas de `gesec_facture` : il décode le JSON du LLM et reconstruit
localement HT/TTC/TVA quand deux de ces montants sont fournis. La devise est
conservée telle que renvoyée par le LLM, sans validation croisée avec
l'en-tête.

C'est le gold, qui a accès à `gesec_facture`, qui complète les montants manquants
via les taux de l'en-tête puis valide la facture avant insertion : cohérence
`HT + TVA = TTC` à 0,02 € par ligne, totaux à 0,5 % de l'en-tête. Une
incohérence rejette toute la facture.

La construction des lignes gold se fait dans `gold.facture_ligne` :
`transform_to_gold` émet les lignes XML, puis Factur-X, puis les lignes PDF des
seules factures sans aucune ligne XML/Factur-X. L'objet PDF est porté par
`GoldFacture` et rempli par `gold.facture` à la construction de `gesec_facture`,
pas par un update a posteriori. La source des lignes PDF porte le nom du PDF
(`extract_pdf:<nom_pdf>`), ce qui permet de les distinguer des lignes XML.

L'ordre du launcher est significatif : silver PDF, puis `gold.facture`, puis
`gold.facture_ligne` (qui branche le fallback PDF avant `match_ugap`), puis
`meta_budat`.

## Options écartées

- Traiter les PDF dans le launcher sans table bronze : impossible de reprendre
  un run interrompu sans refaire les appels OCR/LLM, et impossible de distinguer
  une absence de lignes d'un échec d'extraction.
- Insérer les lignes PDF dans le gold avant les lignes XML : risque d'écraser
  ou de dupliquer les lignes du chemin préféré.
- Accepter les factures dont les montants sont incohérents : fausserait les
  agrégats et le classement GM.
- Utiliser un CSV comme interface entre extraction et silver : perd les statuts,
  les erreurs et les empreintes nécessaires au retry.
- Faire lire `gesec_facture` (gold) par le silver pour dériver ou contrôler les
  montants : inverse les couches. Le silver décode ce que le LLM fournit, le
  gold réconcilie avec l'en-tête.
- Comparer la devise des lignes à celle de l'en-tête : les libellés CPRO
  (`Euro européen`) et les codes ISO du LLM ne sont pas comparables, et aucun
  besoin métier ne le justifie aujourd'hui.

## Conséquences

- `manage.py extract_pdf` est une étape indépendante du launcher, avec ses modes
  `new`, `retry`, `reprocess` et `all`, et peut tourner avec `--dry-run`.
- Un run complet enchaîne désormais l'extraction PDF en silver puis le fallback
  gold ; `classify_gm` lit l'objet de facture ainsi obtenu.
- Le coût OCR/LLM est proportionnel aux seules factures sans pivot XML, et les
  relances ne rejouent que les erreurs sélectionnées.
