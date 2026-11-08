from django.db import models
from django.db.models import Avg, Count, Max, Min, Sum


class MetaBudat(models.Model):
    """Méta-table BUDAT × factures CPRO × lignes, reconstruite en SQL brut par le pipeline.

    Modèle non géré : la table `gesec_meta_budat` est créée par
    `gesec/data/pipeline/layer_3_gold/meta_budat.py` (CREATE TABLE AS), hors migrations.
    """

    source = models.TextField()
    source_idx = models.IntegerField(primary_key=True)
    annee = models.TextField()
    facture = models.TextField()
    facture_ref = models.TextField()
    facture_date_str = models.TextField()
    facture_date = models.DateField(null=True)
    date_payment_str = models.TextField()
    date_payment = models.DateField(null=True)
    ej = models.TextField()
    marche = models.TextField()
    seej = models.TextField()
    facture_fi = models.TextField()
    societe = models.TextField()
    cc = models.TextField()
    pce = models.TextField()
    txt50 = models.TextField()
    activite = models.TextField()
    description = models.TextField()
    libelle_budat = models.TextField()
    fournisseur_budat = models.TextField()
    fournisseur_siren_budat = models.TextField()
    service_budat = models.TextField()
    montant = models.DecimalField(max_digits=18, decimal_places=2)
    montant_ligne_ttc = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    id_cpro = models.TextField(null=True)  # noqa: DJ001
    numero = models.TextField(null=True)  # noqa: DJ001
    facture_ttc = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    gm_multi = models.BooleanField(null=True)
    budat_gm = models.TextField()
    budat_segment = models.TextField()
    budat_domaine = models.TextField()
    cpro_gm = models.TextField()
    cpro_segment = models.TextField()
    cpro_domaine = models.TextField()
    pred_gm = models.TextField()
    pred_segment = models.TextField()
    pred_domaine = models.TextField()
    gm = models.TextField()
    segment = models.TextField()
    domaine = models.TextField()
    ministere = models.TextField()
    service = models.TextField()
    destinataire_service = models.TextField(null=True)  # noqa: DJ001
    fournisseur_facture = models.TextField(null=True)  # noqa: DJ001
    est_ugap = models.BooleanField(null=True)
    line_id = models.TextField(null=True)  # noqa: DJ001
    item_name = models.TextField(null=True)  # noqa: DJ001
    item_description = models.TextField(null=True)  # noqa: DJ001
    item_reference = models.TextField(null=True)  # noqa: DJ001
    quantity = models.DecimalField(max_digits=18, decimal_places=6, null=True)
    unit_price = models.DecimalField(max_digits=18, decimal_places=6, null=True)
    montant_ligne_ht = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    fournisseur_in_fine_designation = models.TextField(null=True)  # noqa: DJ001
    fournisseur_in_fine_siren = models.TextField(null=True)  # noqa: DJ001
    cas = models.TextField()

    FILTERABLE = frozenset(
        {
            "annee",
            "cas",
            "source",
            "ministere",
            "segment",
            "domaine",
            "gm",
            "service",
            "fournisseur_in_fine_siren",
            "id_cpro",
        }
    )
    ICONTAINS = frozenset({"fournisseur_budat", "fournisseur_in_fine_designation"})
    RANGE = frozenset({"montant", "facture_date"})
    GROUPABLE = FILTERABLE | {"fournisseur_budat", "fournisseur_in_fine_designation"}
    ORDERABLE = frozenset({"facture_date", "montant", "annee"})
    NUMERIC = frozenset({"montant", "montant_ligne_ttc", "montant_ligne_ht", "facture_ttc", "quantity", "unit_price"})
    AGG_FUNCS: dict[str, type[Sum | Avg | Count | Min | Max]] = {
        "sum": Sum,
        "avg": Avg,
        "count": Count,
        "min": Min,
        "max": Max,
    }

    class Meta:
        managed = False
        db_table = "gesec_meta_budat"

    def __str__(self) -> str:
        return f"{self.facture} ({self.source_idx})"
