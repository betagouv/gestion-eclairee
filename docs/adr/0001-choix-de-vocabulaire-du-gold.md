# Choix de vocabulaire du gold

Statut : accepté

Le vocabulaire du gold privilégie les noms précis des sources quand le terme
générique ferait perdre de l'information. `numero_du_bon_de_commande` est
conservé car un engagement juridique peut être un bon de commande, un marché,
etc. ; l'EJ reste la clé de rapprochement entre les systèmes, pas le nom du
champ. `gm` est conservé tel quel tant qu'il ne porte que le segment du groupe
de marchandises — le remplir avec le groupe complet est un TODO. Les montants
seront homogénéisés en `montant_ht` et `montant_ttc`.

## Options écartées

Renommer vers le vocabulaire canonique (`ej`, `segment`) : écarté car cela
perdrait la précision du bon de commande et préjugerait du contenu futur de
`gm`.

## Conséquences

Une migration de renommage est à prévoir pour les montants ; aucune action
n'est requise pour `gm` et `numero_du_bon_de_commande` tant que le TODO du GM
complet n'est pas pris.
