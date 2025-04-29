import uuid
from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class UserBase(SQLModel):
    login_type: str | None = Field(default=None)  # github, google, email
    profile_img: str | None = Field(default=None)  # base64
    email: str | None = Field(default=None)
    username: str | None = Field(default=None)

    # personal info
    # academic information
    major: str | None = Field(default=None)
    minor: str | None = Field(default=None)
    graduation_year: int | None = Field(default=None)

    # personal information
    interests: list[str] | None = Field(default=None, sa_column=Column(JSON))
    personality_traits: list[str] | None = Field(default=None, sa_column=Column(JSON))
    schedule: str | None = Field(default=None)
    bio: str | None = Field(default=None)

    def __str__(self):
        return f"""
        Login Type: {self.login_type}
        Major: {self.major}
        Minor: {self.minor}
        Graduation Year: {self.graduation_year}
        Interests: {', '.join(self.interests)}
        Personality Traits: {', '.join(self.personality_traits)}
        Bio: {self.bio}
        Schedule: {self.schedule}
        """


class User(UserBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    uuid: str = Field(default=str(uuid.uuid4()))
    hashed_password: str | None = Field(default=None)
    reset_token: str | None = Field(default=None)
    reset_token_expiry: datetime | None = Field(default=None)


class UserCreate(UserBase):
    password: str | None = Field(default=None)


class UserRead(UserBase):
    uuid: str


class UserUpdate(SQLModel):
    profile_img: str | None = None
    email: str | None = None
    password: str | None = None
