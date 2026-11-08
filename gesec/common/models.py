from typing import override
from urllib.parse import urlsplit

from django.contrib.auth import models as auth_models
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from oauth2_provider.models import AbstractApplication


class BaseModel(models.Model):
    """
    Serves as an abstract base model for other models.

    Includes fields common to all models: a UUID primary key and creation/update timestamps.
    """

    created_at = models.DateTimeField(
        auto_now_add=True,
        editable=False,
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        editable=False,
    )

    class Meta:
        abstract = True

    def save(
        self,
        *,
        force_insert=False,
        force_update=False,
        using=None,
        update_fields=None,
    ):
        """
        Overrides the default save method to ensure the 'updated_at' field is always updated
        unless explicitly excluded.

        Args:
            force_insert (bool): If True, forces the creation of a new record.
            force_update (bool): If True, forces the update of an existing record.
            using (str): The database alias to use for the query.
            update_fields (list): The list of fields to update. If provided, only these fields
                                 will be updated. If 'updated_at' is not in the list, it will
                                 be added unless explicitly excluded with '-updated_at'.

        Returns:
            None
        """
        if update_fields is not None:
            update_fields = list(update_fields) if update_fields else []
            # Remove '-updated_at' from update_fields if present to allow updating 'updated_at'
            if "-updated_at" in update_fields:
                update_fields.remove("-updated_at")
            # Add 'updated_at' to update_fields if not already present to ensure it's updated
            elif "updated_at" not in update_fields:
                update_fields.append("updated_at")
        return super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=None,
            update_fields=update_fields,
        )


class UserManager(auth_models.UserManager):
    """Custom manager for User model with additional methods."""

    @override
    def get_by_natural_key(self, username):
        """Make sure we dont return user if username is falsy."""
        if not username:
            return self.none()
        return super().get_by_natural_key(username=username)


class User(auth_models.AbstractBaseUser, auth_models.PermissionsMixin, BaseModel):
    sub = models.CharField(
        "sub",
        max_length=255,
        unique=True,
        blank=True,
        null=True,
    )

    full_name = models.CharField("nom complet", max_length=100, null=True, blank=True)  # noqa: DJ001
    short_name = models.CharField("nom court", max_length=20, null=True, blank=True)  # noqa: DJ001

    email = models.EmailField(unique=True, blank=True, null=True)  # noqa: DJ001

    # Unlike the "email" field which stores the email coming from the OIDC token, this field
    # stores the email used by staff users to login to the admin site
    admin_email = models.EmailField("adresse e-mail de connection à l'admin", unique=True, blank=True, null=True)

    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into this admin site."),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this user should be treated as active. Unselect this instead of deleting accounts."
        ),
    )

    objects = UserManager()

    USERNAME_FIELD = "admin_email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email or self.admin_email or str(self.pk)


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


def is_loopback_redirect_uri(uri: str) -> bool:
    try:
        parsed = urlsplit(uri)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() in LOOPBACK_HOSTS


class OAuthApplication(AbstractApplication):
    """Application OAuth de l'AS : client public, flux authorization code, redirect loopback."""

    class Meta(AbstractApplication.Meta):
        swappable = "OAUTH2_PROVIDER_APPLICATION_MODEL"

    def clean(self) -> None:
        super().clean()
        if self.client_type != self.CLIENT_PUBLIC:
            raise ValidationError(
                {"client_type": _("Seuls les clients publics (token_endpoint_auth_method=none) sont autorisés.")}
            )
        if self.authorization_grant_type != self.GRANT_AUTHORIZATION_CODE:
            raise ValidationError({"authorization_grant_type": _("Seul le flux authorization code est autorisé.")})
        redirect_errors = [
            ValidationError(
                _(
                    "L'URI de redirection %(uri)s doit être une boucle locale "
                    "http(s)://127.0.0.1[:port][/chemin] ou http(s)://[::1][:port][/chemin]."
                ),
                params={"uri": uri},
            )
            for uri in self.redirect_uris.strip().split()
            if not is_loopback_redirect_uri(uri)
        ]
        if redirect_errors:
            raise ValidationError({"redirect_uris": redirect_errors})

    @override
    def redirect_uri_allowed(self, uri: str) -> bool:
        """Refuse toute URI non loopback, puis délègue le match exact à DOT.

        Le port reste libre pour les IP loopback en http (RFC 8252 §7.3) ; le
        chemin et la query doivent correspondre exactement à une URI enregistrée.
        Le code d'autorisation reste protégé par le PKCE S256 obligatoire.
        """
        if not is_loopback_redirect_uri(uri):
            return False
        return super().redirect_uri_allowed(uri)
