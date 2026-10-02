import logging
from pathlib import Path

from sqlalchemy import Engine, text

from gesec.data.pipeline.db import create_engine
from gesec.data.pipeline.layer_3_gold.constants import UGAP_SIREN

logger = logging.getLogger(__name__)

TABLE_NAME = "gesec_meta_budat"
SQL_PATH = Path(__file__).with_name("meta_budat.sql")

INDEXES: list[tuple[str, str]] = [
    ("gesec_meta_budat_source_idx", "(source, source_idx)"),
    ("gesec_meta_budat_id_cpro", "(id_cpro)"),
    ("gesec_meta_budat_cas", "(cas)"),
    ("gesec_meta_budat_segment", "(segment)"),
    ("gesec_meta_budat_ministere", "(ministere)"),
    ("gesec_meta_budat_fournisseur_in_fine_siren", "(fournisseur_in_fine_siren)"),
]


def load_query() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def process_to_gold(engine: Engine | None = None) -> None:
    """Reconstruit la méta-table BUDAT à partir de la requête SQL validée.

    La table est recréée dans une transaction : les lecteurs conservent
    l'ancienne version jusqu'au commit, sans verrou long.
    """
    engine = engine or create_engine()
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE_NAME}"))
        conn.execute(text(f"CREATE TABLE {TABLE_NAME} AS {load_query()}").bindparams(ugap_siren=UGAP_SIREN))
        for index_name, columns in INDEXES:
            conn.execute(text(f"CREATE INDEX {index_name} ON {TABLE_NAME} {columns}"))

    with engine.connect() as conn:
        nb_lignes = conn.execute(text(f"SELECT count(*) FROM {TABLE_NAME}")).scalar_one()
        nb_dates_non_parsees = conn.execute(
            text(f"""
                SELECT count(*)
                FROM {TABLE_NAME}
                WHERE (btrim(coalesce(facture_date_str, '')) <> '' AND facture_date IS NULL)
                   OR (btrim(coalesce(date_payment_str, '')) <> '' AND date_payment IS NULL)
            """)
        ).scalar_one()

    logger.info(f"{TABLE_NAME} reconstruite : {nb_lignes} lignes")
    if nb_dates_non_parsees:
        logger.warning(f"{nb_dates_non_parsees} dates non parsées dans {TABLE_NAME}")
