from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import Field

from app.schemas.common import ChatTokenUsage, _JsonBase

ChatRole = Literal["user", "assistant", "tool"]
ToolStatus = Literal["ok", "error"]


class ChatRequest(_JsonBase):
    message: str
    session_id: str


class ChatChunkToken(_JsonBase):
    type: Literal["token"]
    content: str


class ChatChunkToolStart(_JsonBase):
    type: Literal["tool_start"]
    tool_name: str


class ChatChunkToolEnd(_JsonBase):
    type: Literal["tool_end"]
    tool_name: str
    status: ToolStatus


class ChatChunkDone(_JsonBase):
    type: Literal["done"]
    token_usage: ChatTokenUsage


class ChatChunkError(_JsonBase):
    type: Literal["error"]
    message: str


ChatChunk = Annotated[
    Union[ChatChunkToken, ChatChunkToolStart, ChatChunkToolEnd, ChatChunkDone, ChatChunkError],
    Field(discriminator="type"),
]


class ChatMessageResponse(_JsonBase):
    id: str
    session_id: str
    role: ChatRole
    content: str
    tool_name: str | None
    token_usage: ChatTokenUsage | None
    created_at: datetime
