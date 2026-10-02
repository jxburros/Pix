class PixError(Exception):
    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.details = details

    def as_dict(self):
        return {"error": self.code, "message": str(self), **self.details}


def require(condition, message, code="invalid_operation", **details):
    if not condition:
        raise PixError(code, message, **details)
