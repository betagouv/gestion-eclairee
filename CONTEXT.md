# Gestion Éclairée

Gestion Éclairée analyse les dépenses publiques à partir des factures
téléchargées depuis Chorus Pro et des données ODA et BUDAT.

## Vocabulaire

Chaque terme canonique est le terme final du résultat ; les libellés utilisés
par les sources sont tracés sous `_Dans les sources_`.

### Sources de données

**Chorus Pro (CPRO)** :
Plateforme de dématérialisation des factures de l'État, utilisée pour
télécharger les factures et des exports CSV de recherche.
_Éviter_ : Chorus

**ODA** :
Système fournissant les données budgétaires associées aux engagements et aux
dépenses ; contribue à définir la liste des factures à télécharger depuis
Chorus Pro.

**BUDAT** :
Système fournissant les informations de paiement des factures ; contribue à
définir la liste des factures à télécharger depuis Chorus Pro.

**Annuaire des services** :
Référentiel des services de l'État (code, désignation, statut) utilisé pour
rattacher chaque service à un ministère.

### Facture et documents

**Facture** :
Document de facturation importé depuis Chorus Pro ; unité de base de l'analyse
des dépenses.
_Éviter_ : dépense

**Identifiant Chorus Pro** :
Identifiant unique d'une facture dans Chorus Pro ; clé d'unicité de la facture
dans le résultat.
_Dans les sources_ : « Identifiant Chorus Pro » (Chorus Pro)
_Synonymes acceptés_ : id_cpro, id CPRO (forme courte préférée dans le code)

**Archive de facture** :
Fichier `.zip` téléchargé depuis Chorus Pro pour une facture donnée, contenant
les versions de la facture et ses pièces jointes.
_Éviter_ : zip

**Facture XML** :
Version XML de la facture produite par le fournisseur ; source préférée pour
les lignes.
_Éviter_ : UBL, facture-xml

**Factur-X** :
Version PDF de la facture contenant un XML embarqué ; utilisée quand la facture
XML est absente.
_Éviter_ : FacturX, facturx

**Pièce jointe (PJ)** :
Document attaché à une facture dans Chorus Pro (bon de commande, bon de
livraison, PDF de la facture...).

### Acteurs

**Émetteur** :
Entreprise ou organisme ayant émis la facture ; peut différer du fournisseur
(facturation déléguée, affacturage).
_Dans les sources_ : « Emetteur » (Chorus Pro)
_Éviter_ : logiciel d'émission

**Fournisseur** :
Entreprise ou organisme ayant exécuté la prestation facturée.
_Dans les sources_ : « Fournisseur » (Chorus Pro), « Nom fournisseur - Clé »
(ODA), « FOURN » (BUDAT)
_Éviter_ : Prestataire, Titulaire

### Rattachement budgétaire

**Engagement juridique (EJ)** :
Engagement pris par un service ; peut prendre la forme d'un bon de commande,
d'un marché, etc. ; clé de rapprochement entre les systèmes.
_Dans les sources_ : « Numéro EJ référencé facture » (ODA), « EJ » (BUDAT),
« NumeroEngagement » (pivot)
_Éviter_ : numéro d'engagement (sauf citation d'un export)

**Bon de commande** :
Forme d'engagement juridique à laquelle une facture peut être rattachée ; le
numéro de bon de commande porté par la facture est plus précis que l'EJ.
_Dans les sources_ : « Numéro du bon de commande » (Chorus Pro)
_Éviter_ : BC

**Domaine** :
Premier niveau de la nomenclature des groupes de marchandises (ex. `33`).
_Dans les sources_ : « Domaine » (ODA)

**Segment** :
Deuxième niveau de la nomenclature des groupes de marchandises (ex. `33.01`).
_Dans les sources_ : « Segment » (ODA)
_Éviter_ : GM

**Groupe de marchandises (GM)** :
Troisième niveau de la nomenclature des groupes de marchandises (ex.
`33.01.04`) ; un groupe de marchandises est composé d'un domaine, d'un segment
et d'un groupe.
_Dans les sources_ : « Groupe de marchandises (P) - Clé » (ODA)

### Organisations

**Destinataire** :
Organisation destinataire de la facture ; son service de rattachement est le
service.
_Dans les sources_ : « Destinataire » (Chorus Pro), « Debiteur » (pivot)
_Éviter_ : débiteur

**Service** :
Unité opérationnelle destinataire d'une facture, identifiée par un code
service.
_Dans les sources_ : « Code service » (annuaire Chorus Pro), « SEDP » (BUDAT)

**Ministère** :
Organisation bénéficiaire d'une facture, au sens large (ministères, autorités,
établissements) ; obtenue par rattachement du service.
_Dans les sources_ : « Ministère » (ODA), « V_Ministère_Service bénéficaire »
(ODA)
_Éviter_ : entité, organisme, administration

**INCONNU** :
Ministère attribué par défaut à un service non rattaché.

### États de facture

**État de la facture** :
État courant d'une facture du point de vue de Chorus Pro, porté par ses
exports.
_Dans les sources_ : « État courant » (Chorus Pro)

**Mise en paiement** :
État d'une facture validée et transmise au paiement dans Chorus Pro. Le
périmètre analysé ne s'y limite pas : le recoupement avec BUDAT fait entrer
des factures dans d'autres états.
