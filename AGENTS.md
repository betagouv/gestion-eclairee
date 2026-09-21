# Gestion Éclairée

Django 5.2 / Python 3.14 (uv). Analyse des dépenses publiques à partir des exports
Chorus Pro (CPRO), ODA et BUDAT. Pipeline ETL bronze/silver/gold + front DSFR.

## Commandes

- Tests : `uv run pytest --no-migrations tests`
  - ciblé : `uv run pytest --no-migrations tests/chemin/test_x.py::test_y`
  - couverture : `uv run pytest --cov=gesec --cov-report html --no-migrations tests`
- Lint/format : `uv run ruff format; uv run ruff check --fix`
- Django : `uv run ./manage.py <commande>` (migrate, shell, launch_pipeline...)
- Pipeline complet : `uv run ./manage.py launch_pipeline [--ministere <code>]`
- Extraction XML : `uv run python -m gesec.data.processors.cpro.pivots_xml -i <in> -o <out>`
- Recette de bout en bout : `./test_recette.sh` (ENV_FILE=../gesec-recette.env)

## Architecture

- `gesec/data/pipeline/layer_1_bronze/` : ingestion brute CSV/XML vers la base
- `gesec/data/pipeline/layer_2_silver/` : normalisation, mapping services → ministères
- `gesec/data/pipeline/layer_3_gold/` : tables métier `Facture` / `FactureLigne`
- `gesec/data/pipeline/launcher.py` : orchestration des 3 couches
- `gesec/data/processors/cpro/` : lecture Factur-X / pivots XML
- `gesec/data/sync/` : listes et téléchargement des exports CPRO
- `gesec/front/` : vues, auth OIDC, rate limiting, templates DSFR
- `gesec/common/models.py` : `BaseModel` ; `gesec/models.py` ré-exporte les modèles
- `tests/` : miroir de `gesec/` ; factories dans `tests/factories/`

## Conventions

- Double quotes, 120 colonnes (ruff), aucun commentaire.
- Tous les fichiers se terminent par un newline, sauf les fichiers de données (CSV, exports...).
- isort : future > stdlib > django > tiers > pandas > first-party > local.
- Migrations exclues de ruff.
- Nouveau modèle : définir dans l'app puis le ré-exporter dans `gesec/models.py`.
- Processors : pandas/SQLAlchemy (écritures avec `chunksize`) ; modèles Django pour le front.

## Commits

Format [Conventional Commits](https://www.conventionalcommits.org/) : les types restent en
anglais (compatibilité outillage), le reste du message est en français.

```
<type>(<scope>): <résumé>

Corps : le pourquoi d'abord, puis le quoi. Puces acceptées.
```

- Types : `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `style`, `chore`, `build`, `ci`.
- Scope optionnel, court, en snake_case : `cpro`, `factur_x`, `oda`, `budat`, `pipeline`,
  `models`, `front`, `auth`, `tests`.
- Résumé impératif présent, minuscule après le `:`, sans point final, ≤ 72 caractères.
- Corps obligatoire dès que le pourquoi n'est pas évident : cause du bug, contrainte,
  choix écartés. Décrire aussi les changements non triviaux du diff.
- Un commit = un changement atomique. Interdits : `ruff`, `WIP`, `Fix imports`.
  Le formatage seul se fond dans le commit fonctionnel ; isolé, il devient `style: ...`.
- Footer `Refs: #<n>` si une issue est concernée.

Exemples :

```
feat(cpro): gère les extractions partielles de Factur-X

extract_factures interrompait tout le lot dès qu'un PDF embarqué manquait,
ce qui bloquait les runs sur des archives incomplètes. Le traitement logge
désormais l'échec fichier par fichier et poursuit avec les suivants.

Refs: #42
```

```
fix(models): rend le champ gm nullable

La contrainte unique sur gm échouait sur les factures sans engagement.
```

## Tests

- Toujours `--no-migrations` (pytest-django).
- `test.env` chargé automatiquement ; premier run : téléchargement encodeur tiktoken.
- Fixtures : `s3_client` (moto), `admin_client` ; factories pytest-factoryboy.
- Postgres requis (DATABASE_URL de `test.env`).

## Environnement

- `ENV_FILE` force l'env chargé ; défaut `../gesec.env`.
- `STORAGE_BACKEND=fs|s3` ; entrées pipeline attendues sous la racine du storage
  (`cpro/exports`, `cpro/factures_unzipped`, `oda/...`, `budat/...`).
- `ALBERT_API_KEY` / `ALBERT_BASE_URL` pour le LLM.
