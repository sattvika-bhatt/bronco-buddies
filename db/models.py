import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel


class UserBase(SQLModel):
    login_type: str | None = Field()  # github, google, email
    profile_img: str | None = Field()  # base64
    email: str | None = Field()
    username: str | None = Field()


class User(UserBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    uuid: str = Field(default=str(uuid.uuid4()))
    hashed_password: str | None = Field(default=None)
    reset_token: str | None = Field(default=None)
    reset_token_expiry: datetime | None = Field(default=None)


class UserCreate(UserBase):
    password: str | None = Field()


class UserRead(UserBase):
    uuid: str


class UserUpdate(SQLModel):
    profile_img: str | None = None
    email: str | None = None
    password: str | None = None
