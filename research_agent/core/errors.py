"""Typed errors. Callers must supply safe messages, never source document text."""


class ResearchAgentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class _CategorizedError(ResearchAgentError):
    error_code = "research_agent_error"

    def __init__(self, message: str) -> None:
        super().__init__(self.error_code, message)


class PathViolation(_CategorizedError):
    error_code = "path_violation"


class IntegrityError(_CategorizedError):
    error_code = "integrity_error"


class ConflictError(_CategorizedError):
    error_code = "conflict_error"


class GateError(_CategorizedError):
    error_code = "gate_error"


class BusyError(_CategorizedError):
    error_code = "busy"


class UnsupportedStage(_CategorizedError):
    error_code = "stage_handler_not_installed"
