"""JWT authentication that refuses suspended accounts.

A suspended user may still hold a valid, unexpired access token. Checking only at
login would leave them authenticated for up to the token lifetime, so the check
belongs here, on every request.
"""
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed


class SuspensionAwareJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if user.is_suspended:
            raise AuthenticationFailed(
                "Ce compte est suspendu.", code="account_suspended"
            )
        return user
