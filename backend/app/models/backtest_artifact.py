"""Immutable evidence, with small expiry tombstones retained after payload cleanup."""
from sqlalchemy import Column, Float, Integer, String, Text
from app.models.scan_report import ScanReportBase


class BacktestArtifact(ScanReportBase):
    __tablename__ = 'backtest_artifacts'
    id = Column(String, primary_key=True)
    schema_version = Column(Integer, nullable=False)
    symbol = Column(String, nullable=False)
    created_at = Column(Float, nullable=False)
    expires_at = Column(Float, nullable=False, index=True)
    payload_json = Column(Text, nullable=True)
