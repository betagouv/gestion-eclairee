# Classification GM hors launcher, dans une table dédiée

Statut : accepté

Le groupe de marchandises (`gm`) du gold provient d'ODA et n'est renseigné que
pour une partie des factures ; il porte un segment (cf. ADR 0001). Pour estimer
un code GM sur les factures qui en sont dépourvues, le pipeline intègre un
classifieur LLM (`gesec/data/classify_gm/`) qui choisit par étapes un domaine, un segment
puis un code feuille.

Ce classifieur **n'est pas appelé par `launch_pipeline`** : chaque facture
coûte trois appels à Albert, avec une latence et un coût incompatibles avec un
run systématique. Il s'exécute via la commande indépendante
`manage.py classify_gm`, qui accepte des filtres de périmètre (`--ministere`,
`--date-min`, `--date-max` sur `date_etat_courant`).

Les prédictions sont écrites dans une **table dédiée `gesec_facture_gm_pred`**,
et non en colonnes sur `Facture` : le GM prédit est distinct du GM de vérité
terrain, peut être recalculé, et sa nature (sortie LLM, modèle, latence,
raisonnement) n'a pas à alourdir le modèle métier. La table est jointe par
`identifiant_chorus_pro` ; les runs sont **incrémentaux** : seules les factures
du périmètre filtré sont envoyées au LLM puis upsertées, le reste est préservé.

## Options écartées

- Colonnes `gm_pred*` sur `Facture` : mélangerait vérité terrain et prédiction
  dans le même modèle et alourdirait le gold.
- Appel dans `launch_pipeline` : coût LLM et latence sur chaque run.
- Recréation complète de la table à chaque run (comme `gesec_meta_budat`) :
  perdrait les prédictions hors du périmètre courant et interdirait le
  traitement incrémental par ministère ou période.

## Conséquences

- La table `gesec_facture_gm_pred` est créée à la volée par la commande
  (DDL embarqué dans `gesec/data/classify_gm/schema.sql`), pas par une migration Django.
- Le paquet `gesec/data/classify_gm/` lit le gold Django (`gesec_facture`,
  `gesec_facture_ligne`) et dérive sa connexion des settings Django ; l'ancienne
  ingestion CSV (`ingest.py`) et ses tables `facture_entete`/`facture_ligne`
  sont supprimées.
- Le mode `new` s'appuie sur l'absence de ligne dans la table de prédictions ;
  `reprocess` la présence.