import logging

from ..db import load_rows_from_table, save_list_pydantic
from ..layer_1_bronze.cpro_annuaire import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME
from .schemas import SilverService
from ..layer_1_bronze.schemas import BronzeCproAnnuaireService

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]

KNOWN_SERVICES = {
    "CGFHJ00075": "SPM",
    "FACDILA075": "SPM",
}


def load_services_from_cpro_annuaire(bronze_table_name: str) -> list[BronzeCproAnnuaireService]:
    return load_rows_from_table(bronze_table_name, BronzeCproAnnuaireService)


def transform(bronze_services: list[BronzeCproAnnuaireService]) -> list[SilverService]:
    silver_services = []
    for bronze_service in bronze_services:
        ministere = map_service(code=bronze_service.code_service, name=bronze_service.libelle_service)
        silver_service = SilverService(
            code=bronze_service.code_service,
            name=bronze_service.libelle_service,
            ministere=ministere,
        )
        silver_services.append(silver_service)
    return silver_services


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
    elif "culture" in name:
        return "CULTURE"
    elif "services du premier ministre" in name:
        return "SPM"
    elif "agriculture" in name:
        return "AGRICULTURE"
    elif "finances" in name:
        return "FINANCES"
    else:
        return "INCONNU"


def process_bronze_to_silver(
    bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
    silver_table_name: str = DEFAULT_TABLE_NAME,
):
    bronze_services = load_services_from_cpro_annuaire(bronze_table_name)
    silver_services = transform(bronze_services)
    save_list_pydantic(silver_services, silver_table_name, if_exists="replace")
