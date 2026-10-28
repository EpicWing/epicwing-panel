from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DdosSample(Base):
    """Ein fertiger 10-Sekunden-Bucket des Verkehrs eines Servers (Maximum der Raten)."""

    __tablename__ = "ddos_samples"

    container: Mapped[str] = mapped_column(String(128), primary_key=True)
    bucket: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)  # Unix-Sekunden
    rx: Mapped[int] = mapped_column(BigInteger)  # Bytes pro Sekunde
    tx: Mapped[int] = mapped_column(BigInteger)
