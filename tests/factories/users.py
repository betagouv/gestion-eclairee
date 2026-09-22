from django.contrib.auth.models import Group

import factory

from gesec.models import User


class UserFactory(factory.django.DjangoModelFactory[User]):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@test.local")

    full_name = "Pierre"
    short_name = "Dupont"


class GroupFactory(factory.django.DjangoModelFactory[Group]):
    class Meta:
        model = Group

    name = factory.Sequence(lambda n: f"group_{n}")
