# app/backends.py
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()

class ShopAwareAuthenticationBackend(ModelBackend):
    """
    Allows login by username OR email.
    Blocks login if shop subscription inactive (except superuser/staff).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        try:
            user = User.objects.get(Q(username=username) | Q(email=username))
        except User.DoesNotExist:
            return None

        if not user.check_password(password):
            return None

        # ✅ allow admin/staff always
        if user.is_superuser or user.is_staff:
            return user

        # ✅ block inactive shop users
        if hasattr(user, "profile") and hasattr(user.profile, "shop"):
            shop = user.profile.shop
            if not shop.is_active:
                return user

        return user
