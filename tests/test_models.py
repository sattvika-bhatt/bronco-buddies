import uuid

import pytest
from pydantic import ValidationError

from db.models import User, UserBase, UserCreate


class TestUserBase:
    def test_normal_str(self):
        """A fully-populated instance should render nicely via ``__str__``."""
        ub = UserBase(
            login_type="github",
            major="Computer Science",
            interests=["coding", "reading"],
            personality_traits=["introverted", "analytical"],
            graduation_year=2025,
            bio="Hello!",
            schedule="MWF 9-11",
        )
        rendered = str(ub)
        assert "Login Type: github" in rendered
        assert "Interests: coding, reading" in rendered
        assert "Personality Traits: introverted, analytical" in rendered

    # Edge

    def test_single_item_lists(self):
        """Single item lists are joined without trailing commas/spaces."""
        ub = UserBase(interests=["coding"], personality_traits=["funny"])
        rendered = str(ub)
        assert "Interests: coding" in rendered
        assert "Personality Traits: funny" in rendered

    def test_empty_lists(self):
        """Empty lists should join to an empty string without error."""
        ub = UserBase(interests=[], personality_traits=[])
        rendered = str(ub)
        assert "Interests:" in rendered  # joined value is empty string
        assert "Personality Traits:" in rendered

    # Invalid

    def test_none_lists_raises(self):
        """``None`` interests/traits cause ``TypeError`` when joined."""
        ub = UserBase()
        with pytest.raises(TypeError):
            _ = str(ub)

    def test_invalid_graduation_year(self):
        """Non-numeric graduation year should fail validation."""
        with pytest.raises((ValidationError, ValueError, TypeError)):
            UserBase(graduation_year="twenty-twenty")


class TestUser:
    def test_uuid_auto_generated(self):
        """UUID field should be auto-populated when omitted."""
        user = User()
        assert user.uuid and isinstance(user.uuid, str)

    def test_uuid_uniqueness(self):
        """Every new ``User`` gets a unique UUID."""
        u1 = User()
        u2 = User()
        assert u1.uuid != u2.uuid

    def test_str_inherited(self):
        """Inherited ``__str__`` from ``UserBase`` works on ``User``."""
        user = User(interests=["a"], personality_traits=["b"], login_type="email")
        assert "Interests: a" in str(user)

    # Edge

    def test_uuid_can_be_overridden(self):
        """Caller may override the auto-generated UUID."""
        custom = str(uuid.uuid4())
        user = User(uuid=custom)
        assert user.uuid == custom

    # Invalid / Behaviour change: SQLModel ORM models skip validation.

    def test_reset_token_expiry_accepts_any_type(self):
        """ORM model (table=True) bypasses Pydantic validation; value is stored verbatim."""
        val = "not-a-datetime"
        user = User(reset_token_expiry=val)
        assert user.reset_token_expiry == val


class TestUserCreate:
    def test_password_is_set(self):
        uc = UserCreate(password="secret")
        assert uc.password == "secret"

    def test_inherited_fields(self):
        uc = UserCreate(major="Mathematics")
        assert uc.major == "Mathematics"

    # Edge

    def test_password_can_be_none(self):
        uc = UserCreate()
        assert uc.password is None

    # Invalid

    def test_invalid_password_type(self):
        with pytest.raises((ValidationError, ValueError, TypeError)):
            UserCreate(password=["not", "a", "str"])

    def test_model_dump(self):
        """Model dump should include custom fields verbatim."""
        uc = UserCreate(password="x", major="CS")
        dumped = uc.model_dump()
        assert dumped["password"] == "x" and dumped["major"] == "CS"
