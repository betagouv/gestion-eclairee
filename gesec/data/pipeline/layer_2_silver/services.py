import logging
from typing import TypedDict

from sqlalchemy import text

from .schemas import SilverService
from ..db import create_engine, save_list_pydantic
from ..layer_1_bronze.cpro_export_factures import DEFAULT_TABLE_NAME as BRONZE_DEFAULT_TABLE_NAME

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "silver_" + __name__.split(".")[-1]

KNOWN_SERVICES = {
    "CGFHJ00075": "SPM",
    "FACDILA075": "SPM",
}


class BronzeService(TypedDict):
    code: str
    name: str


def load_services_from_cpro_export(bronze_table_name: str) -> list[BronzeService]:
    engine = create_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text(f"""SELECT DISTINCT 
                        destinataire_code_service,
                        destinataire_service
                    FROM {bronze_table_name}
                 """),
        )
        rows = result.fetchall()
    return [
        {"code": row.destinataire_code_service, "name": row.destinataire_service}
        for row in rows
        if row.destinataire_service and row.destinataire_code_service
    ]




def transform(bronze_services: list[BronzeService]) -> list[SilverService]:
    silver_services = []
    for bronze_service in bronze_services:
        ministere = map_service(code=bronze_service["code"], name=bronze_service["name"])
        silver_service = SilverService.model_validate({**bronze_service, "ministere": ministere})
        silver_services.append(silver_service)
    return silver_services


def map_service(code: str, name: str) -> str:
    fixed_ministere = KNOWN_SERVICES.get(code)
    if fixed_ministere:
        return fixed_ministere
    if "Min Intérieur" in name or "CGF Intérieur" in name or "SGAMI" in name:
        return "INTERIEUR"
    elif "Min Educ" in name or "Centre de Gestion Financière Educ" in name:
        return "EDUCATION"
    elif "Ministères Sociaux" in name:
        return "SOCIAUX"
    elif "Min Finances" in name:
        return "FINANCES"
    elif "Min Justice" in name or "CGF Justice" in name or "Centre Gestion Financière JUSTICE" in name:
        return "JUSTICE"
    elif "Min. Défense" in name:
        return "DEFENSE"
    elif "Min culture" in name:
        return "CULTURE"
    elif "Services du Premier Ministre" in name:
        return "SPM"
    elif "Min Agriculture" in name:
        return "AGRICULTURE"
    else:
        return "INCONNU"


def process_bronze_to_silver(
        bronze_table_name: str = BRONZE_DEFAULT_TABLE_NAME,
        silver_table_name: str = DEFAULT_TABLE_NAME,
):
    bronze_services = load_services_from_cpro_export(bronze_table_name)
    silver_services = transform(bronze_services)
    save_list_pydantic(silver_services, silver_table_name, if_exists="replace")
