from typing import Any

from django.db.models import Model


class DataRouter:
    """Route les modèles de données vers la base "data", le reste sur "default".

    Seuls les modèles non gérés alimentés par le pipeline (ex. MetaBudat) vont
    sur "data" ; les modèles applicatifs (User, OAuthApplication, RateLimitCount)
    restent sur "default". La base "data" n'est jamais migrée : ses tables sont
    créées en SQL brut par le pipeline.
    """

    DATA_MODELS = {"gesec.metabudat"}

    def _is_data_model(self, model: type[Model]) -> bool:
        return f"{model._meta.app_label}.{model._meta.model_name}" in self.DATA_MODELS

    def db_for_read(self, model: type[Model], **hints: Any) -> str | None:
        if self._is_data_model(model):
            return "data"
        return None

    def db_for_write(self, model: type[Model], **hints: Any) -> str | None:
        if self._is_data_model(model):
            return "data"
        return None

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool | None:
        return None

    def allow_migrate(self, db: str, app_label: str, model_name: str | None = None, **hints: Any) -> bool | None:
        if db == "data":
            return False
        return None
