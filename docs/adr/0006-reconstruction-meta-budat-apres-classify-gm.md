# Reconstruction de meta_budat après classify_gm

Statut : accepté

`gesec_meta_budat` dépend de `gesec_facture_gm_pred` (cf. ADR 0004), produite par
l'étape `classify_gm` qui vit hors launcher (cf. ADR 0003). Or `classify_gm` lit
lui-même le gold `gesec_facture` / `gesec_facture_ligne` produit par
`launch_pipeline`. Il existe donc une dépendance en boucle entre les deux étapes,
qu'aucun run unique ne peut satisfaire :

```
launch_pipeline  →  gesec_facture / gesec_facture_ligne  →  classify_gm
classify_gm      →  gesec_facture_gm_pred                →  meta_budat
```

La boucle se résout sur **deux runs** : les en-têtes et lignes gold sont stables
d'un run à l'autre, si bien qu'une classification lancée après un
`launch_pipeline` porte sur le bon périmètre, et le run suivant peut construire
`meta_budat` avec les prédictions à jour.

`meta_budat` reste reconstruite en fin de `launch_pipeline` : elle doit refléter
les prédictions disponibles au moment du run. Mais une classification lancée
seule laisse `meta_budat` figée sur les prédictions du run précédent. La commande
`manage.py build_meta_budat` comble ce trou : elle rejoue uniquement
`gold.meta_budat.process_to_gold()` (DDL, reconstruction, index), sans relancer
bronze/silver.

Séquence d'exploitation :

```
launch_pipeline        # gold.facture → gold.facture_ligne → meta_budat
classify_gm            # écrit / rafraîchit gesec_facture_gm_pred
build_meta_budat       # reconstruit meta_budat avec les prédictions à jour
```

`process_to_gold` exécute le DDL de `gesec_facture_gm_pred` avant de reconstruire
la table : au premier run, la prédiction est vide plutôt que de faire échouer le
`CREATE TABLE`.

## Options écartées

- Chaîner `classify_gm` dans `launch_pipeline` (option `--with-classify`) :
  contredit l'ADR 0003 (coût et latence LLM incompatibles avec un run
  systématique).
- Sortir les prédictions du SQL de `meta_budat` et les exposer par jointure côté
  consommateur : déplace la logique métier et casse la cascade d'arbitrage
  (cf. ADR 0004) définie dans la table.
- Retirer `meta_budat` de la fin de `launch_pipeline` : priverait le run complet
  d'une méta-table à jour quand la classification est à jour.

## Conséquences

- Deux points d'entrée appellent la même fonction `meta_budat.process_to_gold` :
  la fin de `launch_pipeline` et la commande `build_meta_budat`.
- Après chaque `classify_gm` non suivi d'un `launch_pipeline` complet, exécuter
  `build_meta_budat` pour propager les prédictions.
