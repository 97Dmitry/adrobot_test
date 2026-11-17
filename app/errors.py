class DomainError(Exception):
    def __init__(self, message: str, status: int = 422, code: str = "invalid", details=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details or {}


class RemoteError(DomainError):
    def __init__(self, message: str, remote_status: int | None = None, uncertain: bool = False):
        super().__init__(message, 502, "keitaro_error")
        self.remote_status = remote_status
        self.uncertain = uncertain
