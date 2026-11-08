import django_filters

from gesec.front.api.models import MetaBudat


class MetaBudatFilter(django_filters.FilterSet):
    fournisseur_budat = django_filters.CharFilter(lookup_expr="icontains")
    fournisseur_in_fine_designation = django_filters.CharFilter(lookup_expr="icontains")
    montant = django_filters.RangeFilter()
    facture_date = django_filters.DateFromToRangeFilter()

    class Meta:
        model = MetaBudat
        fields = sorted(MetaBudat.FILTERABLE)
