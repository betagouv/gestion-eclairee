# API REST meta_budat pour agent LLM

Statut : accepté

La méta-table `gesec_meta_budat` (table SQL brute reconstruite par le pipeline,
sans modèle géré) est exposée en lecture seule à l'agent LLM via `/api/`, le
serveur MCP ne faisant que forwarder le Bearer (ADR 0008).

```
agent MCP --Bearer--> mcpserver (passe-plat) --Bearer--> Django /api/meta-budat/
```

## Décisions

- **Modèle non géré** : `gesec.front.api.models.MetaBudat`
  (`managed = False`, `db_table = "gesec_meta_budat"`), ré-exporté dans
  `gesec/models.py`. Aucun champ `gm_list` (tableau) exposé en v1.
- **List uniquement** : `GET /api/meta-budat/` — pas de `retrieve`, la table
  n'a pas de clé primaire stable.
- **Route unique** : `GET /api/meta-budat/` — pas de `retrieve`, la table
  n'a pas de clé primaire stable.
- **Permission** : permission Django **globale** `gesec.api_access`, déclarée
  dans `User.Meta.permissions` (attachée à `User`, pas à la table) et créée
  automatiquement par le signal `post_migrate` `create_permissions` ; vérifiée
  par `ApiAccessPermission` (`user.has_perm`). Aucun scoping par ministère en
  v1 ; `get_queryset` reste le point d'ancrage pour un futur périmètre.
- **Plafond dur de 25 lignes** (`MAX_ROWS`), appliqué aux listes **et** aux
  agrégats — jamais plus, sans pagination par page.
- **Rate limit global de 200 requêtes/jour** sur toutes les routes `/api/`
  (`ApiRateLimitMiddleware`, clé globale `api` dans `RateLimitCount`, 429 +
  `Retry-After`) — le MCP forwardant vers `/api/` est ainsi borné aussi.
- **Filtres** : `django-filter` (`MetaBudatFilter`) — égalité sur les champs
  de `MetaBudat.FILTERABLE`, `icontains` sur `fournisseur_budat` et
  `fournisseur_in_fine_designation`, `RangeFilter` sur `montant`
  (`montant_min`/`montant_max`), `DateFromToRangeFilter` sur `facture_date`
  (`facture_date_after`/`facture_date_before`). Toutes les valeurs passent en
  paramètres liés par l'ORM ; seuls les noms de champs/lookups proviennent des
  allowlists.
- **Mode ligne / mode agrégat sur la même route** : la présence de `group_by`
  ou de `agg` déclenche le mode agrégat. `group_by=champ1,champ2` et
  `agg=func:champ` (répétable ; `func` ∈ `sum, avg, count, min, max`, `champ`
  numérique ou `*` pour `count`). Rendu par `.values().annotate()` (ORM), aucun
  SQL concaténé. Tout champ ou fonction inconnu → **400** (rejet, pas
  d'ignorance silencieuse). Sans `group_by`, renvoie une ligne d'agrégat
  global. Les filtres s'appliquent dans les deux modes (en mode agrégat, via le
  filterset seul — `OrderingFilter` est exclu pour ne pas ordonner sur un champ
  hors GROUP BY).
- **Tri** : paramètre `ordering` (champs séparés par des virgules, préfixe `-`
  pour desc). En mode ligne, `OrderingFilter` sur l'allowlist `ORDERABLE`. En
  mode agrégat, chaque terme doit être un champ de `group_by` **ou** un nom
  d'annotation (`func_champ`, `count_all`), sinon **400** — ce qui permet les
  « top N » (`ordering=-sum_montant`). **Aucun ordre par défaut** en mode
  agrégat : sans `ordering`, l'ordre renvoyé est celui de l'API.
- **Schéma** : `GET /api/meta-budat/schema/` renvoie les allowlists
  (filtrable, icontains, range, groupable, orderable, numérique, fonctions
  d'agrégation, règle du déclencheur d'agrégat, règle du tri, `max_rows`) pour
  l'auto-découverte par l'agent.
- **Outils MCP** : `meta_budat_query` (filtres + `group_by`/`agg`/`ordering`
  optionnels, même route) et `meta_budat_schema` dans `mcpserver/server.py`,
  qui forwardent le Bearer reçu via `forward_authorization`.

## Cas d'usage visés

Deux questions types de l'agent, traduites mécaniquement en requête GET sur la
route unique (fournisseur et segment anonymisés) :

1. « Quels sont les principaux fournisseurs sur un segment donné ? »
   → `?segment=<segment>&group_by=fournisseur_budat&agg=sum:montant&ordering=-sum_montant`
2. « Quels ministères dépensent le plus chez un fournisseur donné ? »
   → `?fournisseur_budat=<fournisseur>&group_by=ministere&agg=sum:montant&ordering=-sum_montant`

Le tri sur l'agrégat (`ordering=-sum_montant`) est ce qui rend ces « top N »
 possibles ; le plafond de 25 lignes borne le résultat.

## Options écartées

- DRF `DjangoModelPermissions` / permission attachée à `MetaBudat` : écarté au
  profit d'une permission **globale** `api_access` sur `User` (la permission
  ne dépend pas d'une ressource précise).
- Route d'agrégation séparée (`/api/meta-budat/aggregate/`) : écartée — une
  seule route, le mode agrégat étant déclenché par la présence de
  `group_by`/`agg`.
- Ordre par défaut en mode agrégat (ex. première annotation décroissante) :
  écarté — l'agent passe explicitement `ordering`, l'API n'impose rien.
- Pagination par pages (`PageNumberPagination`) : écartée — un plafond dur
  opaque de 25 lignes suffit et ne donne pas de paramètre à abuser.
- `retrieve` par identifiant : écarté, pas de PK stable sur la méta-table.
- GraphQL : écarté — la table est plate, le DSL GET (filtres + group_by/agg)
  suffit et l'ORM fait le travail d'agrégation dans les deux cas.
- Requêtes SQL libres / text-to-SQL : écarté — surface d'injection et scoping
  ingérable ; l'agent n'a que des allowlists.

## Conséquences

- Nouvelle dépendance `django-filter`.
- La table `gesec_meta_budat` doit exister en base de test : les tests la
  créent via `schema_editor.create_model` sur le modèle non géré.
- Pour restreindre par ministère plus tard : ajouter le filtre dans
  `MetaBudatViewSet.get_queryset` (les filtres agent ne peuvent que
  restreindre, jamais élargir).
