from django.contrib.postgres.fields import ArrayField
from django.db import models

from gesec.common.models import BaseModel


class Facture(BaseModel):
    # Source tracking
    source = models.CharField()
    source_idx = models.IntegerField()

    # Identification
    identifiant_chorus_pro = models.CharField()
    numero = models.CharField()

    # Dates
    date_etat_courant = models.DateField()
    date_modification = models.DateField()

    # Montants
    montant_a_payer = models.DecimalField(max_digits=20, decimal_places=10)

    # Fournisseur
    fournisseur_type_d_identifiant = models.CharField()
    fournisseur_identifiant = models.CharField()
    fournisseur_designation = models.CharField()

    # Destinataire
    destinataire_code_service = models.CharField()
    destinataire_service = models.CharField()

    # Autres champs
    devise_de_la_facture = models.CharField()
    numero_du_bon_de_commande = models.CharField()
    numero_de_marche = models.CharField()
    gm = models.CharField(null=True)
    gm_list = ArrayField(models.CharField(), null=True)
    gm_multi = models.BooleanField(blank=True, null=True)
    ministere = models.CharField()

    class Meta:
        verbose_name = "Facture"
        verbose_name_plural = "Factures"
        constraints = [
            models.UniqueConstraint(fields=["identifiant_chorus_pro"], name="unique_identifiant_chorus_pro"),
            models.UniqueConstraint(fields=["source", "source_idx"], name="unique_source_idx"),
        ]
        indexes = [
            models.Index(fields=["numero"], name="idx_facture_numero"),
            models.Index(fields=["gm"], name="idx_facture_gm"),
        ]

    def __str__(self):
        return f"Facture {self.identifiant_chorus_pro}"
