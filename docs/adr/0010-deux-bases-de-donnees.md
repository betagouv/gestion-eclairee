# Deux bases de données : applicative (`default`) et données (`data`)

Statut : accepté

Les données du pipeline (bronze/silver/gold, extraction PDF, classification GM)
sont désormais écrites dans une base Postgres distincte de celle de l'API
Django. Django est configuré avec deux alias dans `DATABASES` :

- `default` (`DATABASE_URL`) : base applicative — `User`, `OAuthApplication`,
  `RateLimitCount`, sessions, admin. C'est la seule base migrée
  (`manage.py migrate` ne touche qu'elle).
- `data` (`DATA_DATABASE_URL`) : base des données — toutes les tables
  bronze/silver/gold créées en SQL brut par le pipeline. **Repli sur
  `DATABASE_URL` si la variable est absente** (dev/test : les deux alias
  pointent vers la même base).

## Décisions

- **Routeur dédié** : `gesec.routers.DataRouter` (`DATABASE_ROUTERS`). Les
  modèles de données non gérés (`gesec.MetaBudat`) sont lus/écrits sur `data` ;
  tout le reste reste sur `default` (`db_for_read`/`db_for_write` renvoient
  `None`). `allow_migrate` renvoie `False` pour `data` : aucune migration ne
  s'y applique, les tables y sont créées par le pipeline.
- **Un seul point d'accès à la base `data`** : `gesec/data/db.py`
  (`get_data_database_url` lu dans `settings.DATABASES["data"]`, et
  `get_connection` pour psycopg — aucune lecture de variable d'environnement
  dans le code). Tous les sous-modules de `gesec.data` y passent :
  `pipeline/db.py` (`create_engine`, donc `execute_sql`,
  `iter_rows_from_table`, `load_rows_from_table`, `TableWriter`) et
  `classify_gm/gold.py`. Aucun changement dans les ~25 modules du pipeline :
  ils passent tous par ces helpers.
- **L'API lit les données sur `data` via l'ORM** : `/api/meta-budat/`
  (`MetaBudat`) est routé vers `data` ; le MCP ne change pas (passe-plat HTTP).
- **Tests** : `DATA_DATABASE_URL` non défini → `data` = miroir de `default`
  (même base de test, Django déduplique la création). Les tests data déclarent
  `databases="__all__"` pour que l'alias `data` soit configuré (son `NAME` est
  alors réécrit vers la base de test, même en run ciblé) ; les tests ORM sur
  `MetaBudat` créent la table via `connections["data"]`.

## Options écartées

- Un seul alias avec un schéma séparé (`search_path`) : écarté — la séparation
  demandée est physique (base distincte), pas logique.
- Router par `app_label` : écarté — `User`/`OAuthApplication` et `MetaBudat`
  partagent l'app `gesec` ; le routage se fait par modèle (`DATA_MODELS`).
- Rendre `DATA_DATABASE_URL` obligatoire partout : écarté — casse le setup
  local existant sans bénéfice ; le repli sur `DATABASE_URL` garde dev/test
  simples, la séparation n'étant effective que là où la variable est définie.

## Conséquences

- En production, définir `DATA_DATABASE_URL` (base dédiée) ; sans la variable,
  le pipeline écrirait dans la base applicative comme avant.
- `scripts/synthese_budat.py` reste paramétré par variable d'env nommée
  (`PROD_DB_URL`, etc.) : pointer dessus la base `data`.
- Les sauvegardes/restauration et droits Postgres doivent couvrir les deux
  bases séparément.
