from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str | None = None
    model: str = "openai:gpt-4o"
    system_prompt: str | None = None


class ConversationResponse(BaseModel):
    id: str
    title: str | None = None
    model: str
    created_at: str
    updated_at: str


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]
    total: int


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    tokens: int | None = None
    created_at: str


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int


class ChatRequest(BaseModel):
    model: str = "openai:gpt-4o"
    conversation_id: str | None = None
    system_prompt: str | None = None
    messages: list[MessageCreate]
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1000, ge=1, le=100_000)
    stream: bool = False


class ChatResponse(BaseModel):
    conversation_id: str
    message: MessageResponse
    usage: dict


class ModelResponse(BaseModel):
    id: str
    name: str
    provider: str
    context: int
    max_output: int
    supports_stream: bool


class ModelListResponse(BaseModel):
    models: list[ModelResponse]
