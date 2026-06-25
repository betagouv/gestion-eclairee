from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CategoriePJ(str, Enum):
    FACTURE_PDF = "Facture PDF"
    DUPLICATA_FACTUR_X = "DUPLICATA_FACTUR-X"
    FACTURE_XML = "Facture XML"
    BON_DE_COMMANDE = "Bon de commande"
    BON_DE_LIVRAISON = "Bon de livraison"
    ANNEXE = "Document annexe"
    PJ_STANDARD = "Pièce jointe standard"
    BORDEREAU_DE_SUIVI = "Bordereau de suivi"


class TypePJ(str, Enum):
    TYPE_1 = "01"
    TYPE_2 = "02"


class Renvoi(str, Enum):
    OUI = "Oui"
    NON = "Non"
    RECYCLEE = "Recyclée"


# ModePaiement
class ModePaiement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    Code: str
    Libelle: str


# Montants
class Montants(BaseModel):
    model_config = ConfigDict(extra="forbid")
    MontantHT: float
    MontantTTC: float
    MontantNetAPayer: float


# TVA
class TVA(BaseModel):
    model_config = ConfigDict(extra="forbid")
    Taux: float  # pourcentage
    BaseHt: float
    MontantTVA: float


# Engagement
class Engagement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    NumeroEngagement: str  # 10 digits
    NumeroMarche: Optional[str] = None


# Ligne
class Ligne(BaseModel):
    model_config = ConfigDict(extra="forbid")
    NumOrdre: int = Field(alias="@NumOrdre")
    ReferenceProduit: str | None = None
    PrixUnitaire: float
    Quantite: float
    MontantHT: float
    TauxTVA: float | None = None  # pourcentage


# PJ
class PJ(BaseModel):
    model_config = ConfigDict(extra="forbid")
    NumOrdre: int = Field(alias="@NumOrdre")
    Contenu: str  # base64
    NomPJ: str
    CategoriePJ: CategoriePJ
    TypePJ: TypePJ
    MimeTypePJ: str
    NomPJOrigine: str | None = None


# Fournisseur
class Fournisseur(BaseModel):
    model_config = ConfigDict(extra="forbid")
    TypeIdentifiant: str
    Identifiant: str
    RaisonSociale: str
    CodePays: str
    ModeEmission: str
    ReferenceBancaire: Optional[dict] = None


# Debiteur
class Debiteur(BaseModel):
    model_config = ConfigDict(extra="forbid")
    TypeIdentifiant: str
    Identifiant: str
    Nom: str
    CodeService: str
    NomService: str


# DonneesFacture
class DonneesFacture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    Id: str
    IdFactureOrigine: Optional[str] = None
    IdCPRO: str
    Renvoi: Renvoi
    Type: int
    Cadre: str
    DateEmissionFacture: date
    DateLivraison: date
    DateReception: date
    ModePaiement: ModePaiement
    Devise: str
    Montants: Montants
    TVAs: list[TVA] | None
    Engagement: Engagement
    Lignes: list[Ligne] | None


# CPPFacturePivotUnitaire
class CPPFacturePivotUnitaire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    NumOrdre: int = Field(alias="@NumOrdre")
    Fournisseur: Fournisseur
    Debiteur: Debiteur
    DonneesFacture: DonneesFacture
    PJ: list[PJ]
    CycleDeValidation: dict | None = None


# CPPFactures
class CPPFactures(BaseModel):
    model_config = ConfigDict(extra="forbid")
    Compteur: int = Field(alias="@Compteur")
    CPPFacturePivotUnitaire: list[CPPFacturePivotUnitaire]


# CPPFacturePivot (root)
class CPPFacturePivot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    xmlns_xsi: str = Field(alias="@xmlns:xsi")
    xsi_noNamespaceSchemaLocation: str = Field(alias="@xsi:noNamespaceSchemaLocation")
    Enveloppe: dict
    CPPFactures: CPPFactures
