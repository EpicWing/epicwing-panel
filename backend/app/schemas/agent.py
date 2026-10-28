import uuid

from pydantic import BaseModel, Field


class AgentEnrollRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    public_key: str = Field(min_length=1, max_length=128)
    agent_version: str | None = Field(default=None, max_length=32)


class AgentEnrolled(BaseModel):
    node_id: uuid.UUID
    node_name: str
