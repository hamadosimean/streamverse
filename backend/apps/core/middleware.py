"""Response-header hardening that Django's SecurityMiddleware does not cover."""


class SecurityHeadersMiddleware:
    """Add the headers Django has no setting for.

    `SecurityMiddleware` handles nosniff, referrer-policy and HSTS; clickjacking
    is handled by XFrameOptionsMiddleware. Permissions-Policy and CORP have no
    Django equivalent, so they are set here rather than only at the edge — the
    API must be safe even if it is ever exposed without the reverse proxy in
    front of it.
    """

    # The API renders no UI, so every powerful feature is denied outright.
    PERMISSIONS_POLICY = (
        "accelerometer=(), autoplay=(self), camera=(), display-capture=(), "
        "encrypted-media=(self), fullscreen=(self), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), midi=(), payment=(), picture-in-picture=(self), "
        "usb=(), interest-cohort=()"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", self.PERMISSIONS_POLICY)
        # Same-site only: a JSON response should never be embeddable as a
        # subresource by another origin.
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        return response
