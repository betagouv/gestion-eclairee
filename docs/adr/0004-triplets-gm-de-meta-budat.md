# Triplets GM préfixés par source dans meta_budat

Statut : accepté

`gesec_meta_budat` part de chaque ligne BUDAT et l'éclate sur les lignes de la
facture CPRO rapprochée. Trois sources y portaient un groupe de marchandises
(GM), sous des noms hétérogènes : `gm` de la ligne BUDAT, `gm` de la facture
CPRO (copié jusqu'ici dans une colonne `segment`), et la prédiction LLM de
`gesec_facture_gm_pred` (cf. ADR 0003). Une seule colonne `segment` mélangeait
donc deux niveaux et deux sources, sans exposer le domaine ni le GM prédit.

La table expose désormais **quatre triplets `(domaine, segment, gm)`**, les trois
premiers préfixés par leur source, le quatrième arbitré :

- `budat_domaine`, `budat_segment`, `budat_gm` (ex-`gm_budat`) : GM porté par la
  ligne BUDAT, parfois partiel ou vide.
- `cpro_domaine`, `cpro_segment`, `cpro_gm` : GM de vérité terrain de la facture
  CPRO (ODA), NULL quand la facture est absente.
- `pred_domaine`, `pred_segment`, `pred_gm` : prédiction LLM, NULL quand absente.
- `domaine`, `segment`, `gm` : arbitrage, prédiction > CPRO > BUDAT.

Le préfixe a été préféré au suffixe pour aligner le nom sur l'ordre de lecture
(source puis niveau) et parce que `gm_budat` existait déjà sous cette forme.

L'arbitrage est une **cascade par triplet entier**, pas colonne par colonne :
dès qu'une source fournit un GM, ses trois niveaux sont retenus ensemble. Un
`coalesce` colonne à colonne aurait pu composer un triplet incohérent à partir de
sources différentes.

Les niveaux domaine et segment des sources non prédites sont dérivés par
troncature : `substring(gm from 1 for 2)` pour le domaine,
`substring(gm from 1 for 5)` pour le segment. La prédiction fournit déjà ses
niveaux (`gm_pred_domaine`, `gm_pred_segment`), recopiés tels quels.

Le vide est représenté par une **chaîne vide**, pas `NULL`, pour tous les GM :
les GM bruts sont coalescés en sortie de CTE et après les jointures, ce qui
permet à la cascade d'arbitrage de se lire en `<> ''` au lieu de composer
`is not null` et `nullif`.

La jointure vers la prédiction se fait par `id_cpro = identifiant_chorus_pro` de
la facture rapprochée, et non par le numéro de facture.

## Options écartées

- Suffixer les colonnes (`gm_budat`, `gm_cpro`...) : `budat_gm` existait déjà en
  préfixe ; unifier par préfixe évite deux conventions dans la même table.
- `coalesce` colonne à colonne pour l'arbitrage : autorise un triplet composite
  dont les niveaux proviennent de sources différentes.
- Exposer `gm_pred_raw` (JSONB des étapes LLM) dans la méta-table : volume et
  nature de diagnostic, sans usage analytique ici.
- Conserver `segment` avec son ancienne sémantique (cpro sinon budat) : deux
  niveaux de nomenclature mélangés dans une même colonne.
- Représenter le vide GM par `NULL` : oblige la cascade à tester `is not null`
  et à normaliser chaque source avec `nullif`, pour une sémantique équivalente.

## Conséquences

- `gm_budat` est renommé `budat_gm` ; `segment` change de sémantique pour porter
  l'arbitrage. Aucun consommateur hors `meta_budat.sql` et ses tests n'utilisait
  ces colonnes.
- `gesec_meta_budat` dépend de `gesec_facture_gm_pred` ; une facture présente
  sans prédiction retombe sur CPRO, une facture absente sur BUDAT.
- Le domaine et le segment dérivés sont NULL quand le GM source est vide ou
  absent.