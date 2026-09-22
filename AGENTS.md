# Gestion Éclairée

Django 5.2 / Python 3.14 (uv). Analyse des dépenses publiques à partir des exports
Chorus Pro (CPRO), ODA et BUDAT. Pipeline ETL bronze/silver/gold + front DSFR.

## Commandes

- Tests : `uv run pytest --no-migrations tests`
  - ciblé : `uv run pytest --no-migrations tests/chemin/test_x.py::test_y`
  - couverture : `uv run pytest --cov=gesec --cov-report html --no-migrations tests`
- Lint/format : `uv run ruff format; uv run ruff check --fix; uv run ty check`
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

## Vocabulaire

- `CONTEXT.md` : glossaire métier (termes canoniques et libellés sources). Le
  consulter avant de nommer du code, des modèles ou des champs ; le mettre à
  jour dès qu'un terme est tranché.
- `docs/adr/` : décisions structurantes, numérotées. En créer un pour tout
  choix difficilement réversible, surprenant sans contexte et issu d'un
  arbitrage.

## Conventions

- Double quotes, 120 colonnes (ruff), aucun commentaire.
- Tous les fichiers se terminent par un newline, sauf les fichiers de données (CSV, exports...).
- isort : future > stdlib > django > tiers > pandas > first-party > local.
- Migrations exclues de ruff et de ty.
- Nouveau modèle : définir dans l'app puis le ré-exporter dans `gesec/models.py`.
- Processors : pandas/SQLAlchemy (écritures avec `chunksize`) ; modèles Django pour le front.

## Typage

Vérification : `uv run ty check` (inclus dans le lint). Aucun diagnostic toléré.

- Annoter aux frontières : signatures (paramètres et retour), champs de
  modèles, constantes de module.
- Laisser l'inférence sur les locales : variables de boucle, compréhensions,
  expressions et résultats d'appels évidents.
- N'annoter une locale que pour lever une ambiguïté (`dict`/`list`/`set` vides,
  `json.loads`, `**kwargs` pydantic, retours pandas/SQLAlchemy) ou quand
  l'inférence trompe.
- `-> None` explicite sur les fonctions sans retour.
- Structures explicites : `dict[str, X]`, `list[X]`, `TypedDict` pour les formes
  stables, `Literal` pour les vocabulaires fermés. Jamais de `dict` ou `list` nus.
- Paramètres lus : `Sequence[X]` / `Iterable[X]` plutôt que `list[X]` (invariance).
- `Any` réservé aux frontières non typables (CSV/XML/JSON, `**kwargs` pydantic) ;
  jamais en retour d'une fonction métier.
- Préférer `typing.cast` ciblé ou une garde runtime à `ty: ignore`.

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
