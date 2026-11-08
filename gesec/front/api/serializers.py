from rest_framework import serializers

from gesec.front.api.models import MetaBudat


class MetaBudatSerializer(serializers.ModelSerializer[MetaBudat]):
    class Meta:
        model = MetaBudat
        exclude = ()
