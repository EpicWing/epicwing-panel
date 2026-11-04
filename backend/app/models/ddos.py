from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DdosSample(Base):
    """A finished 10-second bucket of the traffic of a server (maximum of the rates)."""

    __tablename__ = "ddos_samples"

    container: Mapped[str] = mapped_column(String(128), primary_key=True)
    bucket: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)  # Unix-Sekunden
    rx: Mapped[int] = mapped_column(BigInteger)  # Bytes pro Sekunde
    tx: Mapped[int] = mapped_column(BigInteger)


class DdosRollup(Base):
    """Maximum of the traffic of a server in a 5-minute window, kept for 14 days."""

    __tablename__ = "ddos_rollups"

    container: Mapped[str] = mapped_column(String(128), primary_key=True)
    bucket: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)  # Unix-Sekunden
    rx: Mapped[int] = mapped_column(BigInteger)  # Bytes pro Sekunde
    tx: Mapped[int] = mapped_column(BigInteger)
