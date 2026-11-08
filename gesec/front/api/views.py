from django.db.models import Count
from django.db.models.expressions import Combinable

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from gesec.common.models import User
from gesec.front.api.filters import MetaBudatFilter
from gesec.front.api.models import MetaBudat
from gesec.front.api.serializers import MetaBudatSerializer

MAX_ROWS = 100


class HealthcheckView(APIView):
    def get(self, request: Request) -> Response:
        user = request.user
        assert isinstance(user, User)
        return Response({"ok": True, "username": user.email})


class ApiAccessPermission(BasePermission):
    def has_permission(self, request: Request, view: viewsets.ViewSet) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.has_perm("gesec.api_access"))


def parse_agg(specs: list[str]) -> tuple[dict[str, Combinable] | None, str | None]:
    annotations: dict[str, Combinable] = {}
    for spec in specs:
        func, sep, field = spec.partition(":")
        if not sep or func not in MetaBudat.AGG_FUNCS:
            return None, f"agrégat invalide: {spec!r}"
        if field == "*":
            if func != "count":
                return None, f"agrégat invalide: {spec!r}"
            annotations["count_all"] = Count("*")
        elif field in MetaBudat.NUMERIC:
            annotations[f"{func}_{field}"] = MetaBudat.AGG_FUNCS[func](field)
        else:
            return None, f"agrégat invalide: {spec!r}"
    if not annotations:
        annotations["count_all"] = Count("*")
    return annotations, None


class MetaBudatViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = MetaBudat.objects.all()
    serializer_class = MetaBudatSerializer
    permission_classes = [ApiAccessPermission]
    filterset_class = MetaBudatFilter
    ordering_fields = sorted(MetaBudat.ORDERABLE)
    ordering = ["-facture_date"]

    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        group_raw = request.query_params.get("group_by", "")
        group_by = [g for g in group_raw.split(",") if g]
        agg_specs = request.query_params.getlist("agg")

        if not group_by and not agg_specs:
            rows = self.filter_queryset(self.get_queryset())[:MAX_ROWS]
            return Response(self.get_serializer(rows, many=True).data)

        unknown = [g for g in group_by if g not in MetaBudat.GROUPABLE]
        if unknown:
            return Response({"error": f"champs de groupement inconnus: {', '.join(unknown)}"}, status=400)

        annotations, error = parse_agg(agg_specs)
        if error or annotations is None:
            return Response({"error": error}, status=400)

        ordering_raw = request.query_params.get("ordering", "")
        ordering = [o for o in ordering_raw.split(",") if o]
        for term in ordering:
            name = term.removeprefix("-")
            if name not in group_by and name not in annotations:
                return Response({"error": f"champ de tri inconnu en mode agrégat: {term!r}"}, status=400)

        filterset = self.filterset_class(request.query_params, queryset=self.get_queryset())
        if not filterset.is_valid():
            return Response({"error": f"filtre invalide: {filterset.form.errors}"}, status=400)
        queryset = filterset.qs

        if group_by:
            rows = queryset.values(*group_by).annotate(**annotations)
            if ordering:
                rows = rows.order_by(*ordering)
            return Response([dict(row) for row in rows[:MAX_ROWS]])
        return Response([queryset.aggregate(**annotations)])

    @action(detail=False, methods=["get"])
    def schema(self, request: Request) -> Response:
        return Response(
            {
                "table": MetaBudat._meta.db_table,
                "filterable": sorted(MetaBudat.FILTERABLE),
                "icontains": sorted(MetaBudat.ICONTAINS),
                "range": sorted(MetaBudat.RANGE),
                "groupable": sorted(MetaBudat.GROUPABLE),
                "orderable": sorted(MetaBudat.ORDERABLE),
                "numeric": sorted(MetaBudat.NUMERIC),
                "agg_funcs": sorted(MetaBudat.AGG_FUNCS),
                "agg_param": "agg=func:champ (champ numérique ou '*' pour count), ex. agg=sum:montant",
                "group_by_param": "group_by=champ1,champ2",
                "aggregate_trigger": "group_by ou agg présent",
                "ordering_aggregate": (
                    "en mode agrégat, ordering accepte les champs group_by et les noms d'agrégats "
                    "(func_champ, count_all), préfixe - pour desc"
                ),
                "max_rows": MAX_ROWS,
            }
        )
