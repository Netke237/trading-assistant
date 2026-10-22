"""Additive report storage; legacy scan_sessions are never rewritten."""
from sqlalchemy import Column, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase


class ScanReportBase(DeclarativeBase):
    pass


class ScanReport(ScanReportBase):
    __tablename__ = 'scan_reports'
    id = Column(String, primary_key=True)
    category = Column(String, nullable=False, index=True)
    generation = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    envelope_json = Column(Text, nullable=False)
    __table_args__ = (UniqueConstraint('category', 'generation'),)


class ScanReportHead(ScanReportBase):
    __tablename__ = 'scan_report_heads'
    category = Column(String, primary_key=True)
    generation = Column(Integer, nullable=False, default=0)
    latest_id = Column(String, nullable=True)
    usable_id = Column(String, nullable=True)
