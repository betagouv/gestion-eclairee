-- Méta-table BUDAT × factures CPRO × lignes de facture.
--
-- Part de chaque ligne BUDAT et l'éclate en lignes de facture quand c'est possible.
-- Contrat de réconciliation : chaque ligne BUDAT est présente au moins une fois,
-- la somme de `montant` est égale à la somme BUDAT à l'arrondi centime près.
--
-- Jointure facture : ltrim(facture_ref, '0') = ltrim(numero, '0') ; la REF_FAC de
-- BUDAT est peu fiable (113 920 réfs non numériques), la facture retenue en cas de
-- `numero` dupliqué (224 cas) est celle au plus grand id.
-- Repli sur BUDAT quand la facture est absente : service = SEDP, ministère via
-- silver_services, segment = gm_budat tronqué à 2 niveaux (ex. 33.01.04 -> 33.01).
-- Montants TTC : `montant` = prorata du montant BUDAT sur les lignes de la facture
-- (ou montant BUDAT si non éclatée) ; `montant_ligne_ttc` = TTC réel de la ligne.
-- Dates : `*_str` porte la valeur brute (AAAAMMJJ), la colonne sans suffixe la
-- valeur parsée, NULL quand la valeur brute est vide ou non parsable (le
-- pipeline logge alors un WARNING agrégé).
--
-- Cas :
--   facture_absente                       facture BUDAT introuvable dans CPRO
--   facture_sans_lignes                   facture trouvée, pas de XML / Factur-X exploitable
--   lignes_non_ugap                       facture éclatée, fournisseur non UGAP
--   lignes_ugap_avec_fournisseur_in_fine  facture UGAP éclatée, fournisseur in fine rempli
--   lignes_ugap_sans_fournisseur_in_fine  facture UGAP éclatée, pas de matching UGAP
--
-- Limites connues : BUDAT répète le montant facture sur ses lignes comptables
-- (multi-GM) ; ces montants sont conservés tels quels pour préserver la somme.
-- L'onglet DAE de l'export UGAP et la lecture factur-x ne sont pas couverts.
--
-- Contrôle : select cas, count(*) as nb_lignes, round(sum(montant), 2) as montant
--            from gesec_meta_budat group by 1 order by montant desc;

with
budat as (
    select
        source, source_idx, annee, facture, facture_ref, facture_date, date_payment,
        replace(facture_montant, ',', '.')::numeric as montant_budat,
        ej, marche, seej, gm as gm_budat, libelle, fournisseur as fournisseur_budat,
        fournisseur_siren as fournisseur_siren_budat, facture_fi, societe,
        service as service_budat, cc, pce, txt50, activite, description,
        ltrim(facture_ref, '0') as facture_ref_norm
    from bronze_budat_export_augdt
),
facture as (
    select distinct on (ltrim(numero, '0'))
        ltrim(numero, '0') as numero_norm, numero, identifiant_chorus_pro as id_cpro,
        mt_ttc as facture_ttc, gm as segment, gm_list, gm_multi, ministere,
        destinataire_code_service as service_facture, destinataire_service,
        fournisseur_designation as fournisseur_facture, fournisseur_identifiant,
        left(fournisseur_identifiant, 9) = :ugap_siren as est_ugap
    from gesec_facture
    where numero <> ''
    order by ltrim(numero, '0'), id desc
),
ligne_facture as (
    select id_cpro, count(*) as nb_lignes, sum(line_amount_incl_tax) as total_ttc
    from gesec_facture_ligne
    group by id_cpro
),
services as (
    select code, min(ministere) as ministere
    from silver_services
    where coalesce(code, '') <> ''
    group by code
),
base as (
    select
        b.*, f.id_cpro, f.numero, f.facture_ttc, f.segment, f.gm_list, f.gm_multi,
        f.ministere, f.service_facture, f.destinataire_service, f.fournisseur_facture,
        f.fournisseur_identifiant, f.est_ugap, lf.nb_lignes, lf.total_ttc,
        s.ministere as ministere_service_budat,
        case
            when f.id_cpro is null then 'facture_absente'
            when lf.nb_lignes is null then 'facture_sans_lignes'
            else 'facture_avec_lignes'
        end as cas_facture
    from budat b
    left join facture f on f.numero_norm = b.facture_ref_norm
    left join ligne_facture lf on lf.id_cpro = f.id_cpro
    left join services s on s.code = b.service_budat
),
meta_budat_facture as (
    select
        b.source, b.source_idx, b.annee, b.facture, b.facture_ref,
        b.facture_date as facture_date_str,
        case
            when btrim(b.facture_date) ~ '^[0-9]{8}$' then to_date(btrim(b.facture_date), 'YYYYMMDD')
        end as facture_date,
        b.date_payment as date_payment_str,
        case
            when btrim(b.date_payment) ~ '^[0-9]{8}$' then to_date(btrim(b.date_payment), 'YYYYMMDD')
        end as date_payment,
        b.ej, b.marche, b.seej, b.facture_fi, b.societe, b.cc, b.pce, b.txt50, b.activite, b.description,
        b.gm_budat, b.libelle as libelle_budat, b.fournisseur_budat, b.fournisseur_siren_budat, b.service_budat,
        case
            when b.cas_facture = 'facture_avec_lignes' and b.total_ttc > 0
                then round(b.montant_budat * gl.line_amount_incl_tax / b.total_ttc, 2)
            when b.cas_facture = 'facture_avec_lignes'
                then round(b.montant_budat / b.nb_lignes, 2)
            else b.montant_budat
        end as montant,
        gl.line_amount_incl_tax as montant_ligne_ttc,
        b.id_cpro, b.numero, b.facture_ttc, b.gm_list, b.gm_multi,
        coalesce(b.segment, nullif(substring(b.gm_budat from 1 for 5), '')) as segment,
        coalesce(b.ministere, b.ministere_service_budat, 'INCONNU') as ministere,
        coalesce(nullif(b.service_facture, ''), b.service_budat) as service,
        b.destinataire_service, b.fournisseur_facture, b.est_ugap,
        gl.line_id, gl.item_name, gl.item_description, gl.item_reference, gl.quantity, gl.unit_price,
        gl.line_amount_excl_tax as montant_ligne_ht,
        gl.fournisseur_in_fine_designation, gl.fournisseur_in_fine_siren,
        case
            when b.cas_facture = 'facture_absente' then 'facture_absente'
            when b.cas_facture = 'facture_sans_lignes' then 'facture_sans_lignes'
            when not b.est_ugap then 'lignes_non_ugap'
            when gl.fournisseur_in_fine_designation is not null then 'lignes_ugap_avec_fournisseur_in_fine'
            else 'lignes_ugap_sans_fournisseur_in_fine'
        end as cas
    from base b
    left join gesec_facture_ligne gl on gl.id_cpro = b.id_cpro
)
select * from meta_budat_facture;