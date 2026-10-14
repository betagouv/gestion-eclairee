# Archives de facture écrasées au retéléchargement

Statut : accepté

Les archives de facture sont téléchargées depuis Chorus Pro sous le nom
`cpro/factures/facture_<id_cpro>.zip`. Le storage Django était configuré en
non-écrasement (`file_overwrite: False` sur S3, `allow_overwrite: False` sur
le système de fichiers). À chaque `default_storage.save()` sur un nom déjà
présent, `get_available_name` suffixait un identifiant aléatoire, produisant
`facture_<id_cpro>_<slug>.zip`.

Ces doublons sont indésirables : ils s'accumulent à chaque run interrompu ou
repassé, gonflent le stockage, et introduisent un second nom pour une même
facture. Le pipeline les tolère (`re.match(r".*facture_(\d+)")` capture l'id
avant le suffixe), mais toute la logique d'idempotence repose alors sur la
robustesse du regex plutôt que sur le contrat de nommage.

`file_overwrite` / `allow_overwrite` passent donc à `True` : `save()` écrase
désormais un fichier existant au lieu d'en créer une variante. Pour les
archives de facture, le contenu est déterminé par l'id_cpro, donc réécrire le
même chemin est idempotent et souhaité : le retéléchargement corrige une
archive corrompue au lieu d'en empiler une deuxième. Les gardes
`default_storage.exists()` en amont des téléchargements restent en place, donc
le comportement observable ne change que sur collision.

## Options écartées

- Écraser uniquement les zips facture (save explicite par-dessus, sans changer
  la config globale) : laisserait coexister deux régimes d'écriture, l'un
  écrasant, l'autre suffixant, selon le point d'appel.
- Nettoyer les doublons périodiquement sans changer la config : traite le
  symptôme, laisse le mécanisme continuer à produire des doublons.

## Conséquences

- Le contrat de nommage `facture_<id_cpro>.zip` redevient fiable ; un nom
  suffixté signale désormais un résidu d'avant la bascule.
- Un script de nettoyage (voir `gesec/data/sync/`) supprime les doublons
  déjà présents dans le storage ; il est à exécuter une fois sur chaque
  environnement, sur le bucket de production inclus.
- L'audit de la base de production (2026-10-14) n'a trouvé **aucun** id_cpro
  invalide en bronze/silver/gold : tous les identifiants sont des chaînes de
  9 chiffres, sans suffixe. Les doublons S3 n'ont donc pas contaminé les
  tables, seul le stockage était affecté.
