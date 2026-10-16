import os

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Crea una cuenta administradora inicial usando variables privadas de entorno."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_BOOTSTRAP_ADMIN_USERNAME", "").strip()
        password = os.environ.get("DJANGO_BOOTSTRAP_ADMIN_PASSWORD", "")
        email = os.environ.get("DJANGO_BOOTSTRAP_ADMIN_EMAIL", "").strip()
        if not username and not password:
            self.stdout.write("No se solicitó crear un administrador; se omite.")
            return
        if not username or not password:
            raise CommandError(
                "Configura DJANGO_BOOTSTRAP_ADMIN_USERNAME y "
                "DJANGO_BOOTSTRAP_ADMIN_PASSWORD, o elimina ambas variables."
            )

        user_model = get_user_model()
        username_field = user_model.USERNAME_FIELD
        lookup = {username_field: username}
        existing_user = user_model._default_manager.filter(**lookup).first()
        if existing_user:
            if existing_user.is_staff and existing_user.is_superuser:
                self.stdout.write("El administrador inicial ya existe; no se modifica.")
                return
            raise CommandError(
                "El usuario indicado ya existe y no es administrador; "
                "elige otro nombre de usuario."
            )

        user = user_model(**lookup)
        email_field = getattr(user_model, "EMAIL_FIELD", "email")
        if email and any(
            field.name == email_field for field in user_model._meta.fields
        ):
            setattr(user, email_field, email)
        user.is_staff = True
        user.is_superuser = True
        if hasattr(user, "is_active"):
            user.is_active = True
        user.set_password(password)
        try:
            password_validation.validate_password(password, user)
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from error

        with transaction.atomic():
            user.save()
        self.stdout.write(self.style.SUCCESS("Administrador inicial creado."))
