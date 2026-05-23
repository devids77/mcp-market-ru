from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://mcpuser:McpMarket2026Secure@db:5432/mcpmarket"
    DATABASE_URL_SYNC: str = "postgresql://mcpuser:McpMarket2026Secure@db:5432/mcpmarket"
    SERVER_NAME: str = "MCP Market Russia"
    SERVER_URL: str = "https://mcp-market.ru"
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
