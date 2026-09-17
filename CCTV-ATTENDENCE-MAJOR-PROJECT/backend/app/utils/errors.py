"""Domain-level error type used by Phase 2 academic/student APIs.

Routes raise DomainError with a safe error code and message; a single
Flask error handler (registered in create_app) turns it into the
standardized JSON error envelope so no Python exception, SQL statement,
or stack trace is ever sent to a client.
"""


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
