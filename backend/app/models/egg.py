import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Nest(Base):
    """Category for eggs, for example Games or Web."""

    __tablename__ = "nests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Egg(Base):
    """Describes what runs on a server: image, start command, variables, installation."""

    __tablename__ = "eggs"
    __table_args__ = (UniqueConstraint("nest_id", "name", name="uq_eggs_nest_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nest_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nests.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255), default="")
    docker_image: Mapped[str] = mapped_column(String(255))
    # Start command with {{VARIABLE}} placeholders. Empty means: default command of the image.
    startup: Mapped[str] = mapped_column(String(2048), default="")
    # Empty means: SIGTERM.
    stop_command: Mapped[str] = mapped_column(String(255), default="")
    install_script: Mapped[str] = mapped_column(Text, default="")
    # The rest of the Pterodactyl format as JSON text, for import and export.
    config: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EggVariable(Base):
    __tablename__ = "egg_variables"
    __table_args__ = (UniqueConstraint("egg_id", "env_variable", name="uq_egg_variables_env"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    egg_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eggs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    env_variable: Mapped[str] = mapped_column(String(64))
    default_value: Mapped[str] = mapped_column(String(1024), default="")
    description: Mapped[str] = mapped_column(String(255), default="")
    user_editable: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    user_viewable: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Secret values (tokens) are stored encrypted and never returned by the API.
    secret: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Rules in Pterodactyl style, for example required|integer|between:1,100.
    rules: Mapped[str] = mapped_column(
        String(512), default="nullable|string", server_default="nullable|string"
    )
