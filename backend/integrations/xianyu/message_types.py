from typing import Annotated, Literal, Union
from typing_extensions import TypedDict
from pydantic import Field, TypeAdapter


class TextContent(TypedDict):
    type: Literal["text"]
    text: str


class ImageContent(TypedDict):
    type: Literal["image"]
    image_url: str
    width: int
    height: int


Message = Annotated[
    Union[TextContent, ImageContent],
    Field(discriminator="type"),
]

message_adapter = TypeAdapter(Message)
