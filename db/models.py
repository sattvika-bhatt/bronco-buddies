import uuid
from datetime import datetime, timezone
from typing import List

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel


class Match(SQLModel, table=True):
    user_id_1: int | None = Field(default=None, foreign_key="user.id", primary_key=True)
    user_id_2: int | None = Field(default=None, foreign_key="user.id", primary_key=True)

    created_at: datetime | None = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # explicit relationships to disambiguate the two FK columns
    user1: "User" = Relationship(
        back_populates="outgoing_matches",
        sa_relationship_kwargs={"foreign_keys": "[Match.user_id_1]"},
    )
    user2: "User" = Relationship(
        back_populates="incoming_matches",
        sa_relationship_kwargs={"foreign_keys": "[Match.user_id_2]"},
    )


class UserBase(SQLModel):
    login_type: str | None = Field(default=None)  # github, google, email
    created_at: datetime | None = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

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
        interests = self.interests or []
        traits = self.personality_traits or []
        return f"""
        Login Type: {self.login_type}
        Major: {self.major}
        Minor: {self.minor}
        Graduation Year: {self.graduation_year}
        Interests: {', '.join(interests)}
        Personality Traits: {', '.join(traits)}
        Bio: {self.bio}
        Schedule: {self.schedule}
        """


class User(UserBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    uuid: str = Field(default_factory=lambda: str(uuid.uuid4()))
    hashed_password: str | None = Field(default=None)
    reset_token: str | None = Field(default=None)
    reset_token_expiry: datetime | None = Field(default=None)

    waiting_for_match: bool | None = Field(default=False)

    # two directional collections that use the link table
    outgoing_matches: List["Match"] = Relationship(
        back_populates="user1",
        sa_relationship_kwargs={"foreign_keys": "[Match.user_id_1]"},
    )
    incoming_matches: List["Match"] = Relationship(
        back_populates="user2",
        sa_relationship_kwargs={"foreign_keys": "[Match.user_id_2]"},
    )


class UserCreate(UserBase):
    password: str | None = Field(default=None)


class UserRead(UserBase):
    uuid: str


class UserUpdate(SQLModel):
    profile_img: str | None = None
    email: str | None = None
    password: str | None = None
