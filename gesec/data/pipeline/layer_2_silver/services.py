import logging

from ..db import DEFAULT_BATCH_SIZE, TableWriter, iter_rows_from_table
from ..layer_1_bronze.cpro_annuaire import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from ..layer_1_bronze.schemas import BronzeCproAnnuaireService
from .schemas import SilverService

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]

KNOWN_SERVICES = {
    # CGF Hautes Juridictions
    "CGFHJ00075": "SPM",
    # Direction de l'Information Légale et Administrative
    "FACDILA075": "SPM",
    # Autorité de Contrôle des Nuisances Aéroportuaires
    "AAIACNU075": "AAI",
    # Autorité de Sûreté Nucleaire
    "AAIASN1075": "AAI",
    # Commission de Régulation de l'Energie
    "AAIRE00075": "AAI",
}


def transform(bronze_service: BronzeCproAnnuaireService) -> SilverService:
    ministere = map_service(code=bronze_service.code_service, name=bronze_service.libelle_service)
    return SilverService(
        code=bronze_service.code_service,
        name=bronze_service.libelle_service,
        ministere=ministere,
    )


def map_service(code: str, name: str) -> str:
    fixed_ministere = KNOWN_SERVICES.get(code)
    if fixed_ministere:
        return fixed_ministere
    name = name.lower()
    if "intérieur" in name or "sgami" in name:
        return "INTERIEUR"
    elif "educ" in name:
        return "EDUCATION"
    elif "sociaux" in name:
        return "SOCIAUX"
    elif "justice" in name:
        return "JUSTICE"
    elif "défense" in name:
        return "DEFENSE"
    elif " culture" in name:
        return "CULTURE"
    elif "services du premier ministre" in name:
        return "SPM"
    elif "agriculture" in name:
        return "AGRICULTURE"
    elif "min aff etr" in name:
        return "MEAE"
    elif "finances" in name or "centre de gestion financière" in name:
        return "FINANCES"
    elif "cpcm" in name:
        cpcm_agri = ["Lorraine", "Haute-Normandie"]
        for cpcm in cpcm_agri:
            if cpcm in name:
                return "AGRICULTURE"
        else:
            return "ECOLOGIE"
    elif "ecologie" in name or "metl" in name:
        return "ECOLOGIE"
    else:
        return "INCONNU"


def process_bronze_to_silver(
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
    silver_table_name: str = DEFAULT_TABLE_NAME,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    rows = iter_rows_from_table(bronze_table_name, BronzeCproAnnuaireService, batch_size=batch_size)
    with TableWriter(silver_table_name, SilverService, batch_size=batch_size) as writer:
        for bronze in rows:
            writer.add(transform(bronze))
