class FluxRunError(Exception):
    """Base error for all server and transport failures."""

class AuthenticationError(FluxRunError): pass
class AuthorizationError(FluxRunError): pass
class NotFoundError(FluxRunError): pass
class ConflictError(FluxRunError): pass
class ValidationError(FluxRunError): pass
class TransportError(FluxRunError): pass
class RateLimitError(FluxRunError): pass
