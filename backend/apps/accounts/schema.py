"""drf-spectacular extensions.

Without this, spectacular cannot recognise our JWT authentication subclass and
emits every protected endpoint with no security scheme — the generated docs would
show authenticated routes as if they were public.
"""
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SuspensionAwareJWTScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.SuspensionAwareJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "Access token from POST /api/auth/jwt/create/. "
                "Suspended accounts are rejected on every request, not only at login."
            ),
        }
