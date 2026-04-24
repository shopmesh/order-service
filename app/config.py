from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mongo_uri: str = "mongodb://mongo:27017"
    db_name: str = "orderdb"
    auth_service_url: str = "http://auth-service:3001"
    product_service_url: str = "http://product-service:3002"
    port: int = 3003

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
