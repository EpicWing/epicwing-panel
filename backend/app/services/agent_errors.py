"""Turn errors that an agent reports into messages for users.

The raw text of an agent (often a Docker error with container IDs and addresses) is only for
admins. Users see a short message for the error code, the raw text is in the log and in the
Audit-Log.
"""

import logging

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

GENERIC_MESSAGE = "Something went wrong. Please try again or contact support."

# Error code of the agent -> message for users. Unknown codes get GENERIC_MESSAGE.
MESSAGES = {
    "PORT_IN_USE": (
        "The server could not be started because a network port is in use on this node. "
        "Please contact support."
    ),
    "CONTAINER_MISSING": (
        "The server container does not exist on the node. "
        "Try reinstalling the server or contact support."
    ),
    "BACKUP_RUNNING": "A backup is running for this server. Try again when it has finished.",
    "NODE_BUSY": "The node is busy right now. Please try again in a moment.",
}

MAX_TECHNICAL = 1024


def user_message(code: str | None) -> str:
    return MESSAGES.get(code or "", GENERIC_MESSAGE)


class AgentFailure(HTTPException):
    """An agent command failed. detail is the message for users.

    technical is the raw text of the agent. It is only returned if the endpoint
    sets expose_technical for an admin.
    """

    def __init__(self, code: str | None, technical: str | None) -> None:
        super().__init__(status.HTTP_502_BAD_GATEWAY, user_message(code))
        self.code = code or "AGENT_ERROR"
        self.technical = (technical or "")[:MAX_TECHNICAL]
        self.expose_technical = False
        log.warning("agent command failed (%s): %s", self.code, self.technical)


async def agent_failure_handler(_: Request, exc: AgentFailure) -> JSONResponse:
    body: dict[str, str] = {"detail": str(exc.detail), "code": exc.code}
    if exc.expose_technical and exc.technical:
        body["technical"] = exc.technical
    return JSONResponse(body, status_code=exc.status_code)
