from app.schemas import SectorTile

MOCK_SECTORS: list[SectorTile] = [
    SectorTile(key='XLK',  name='Technology',             changePct=1.24,  status='PASS'),
    SectorTile(key='XLC',  name='Comm. Services',          changePct=0.86,  status='PASS'),
    SectorTile(key='XLY',  name='Consumer Discretionary',  changePct=0.42,  status='PASS'),
    SectorTile(key='XLI',  name='Industrials',             changePct=0.18,  status='CAUTION'),
    SectorTile(key='XLF',  name='Financials',              changePct=0.05,  status='CAUTION'),
    SectorTile(key='XLP',  name='Consumer Staples',        changePct=-0.08, status='CAUTION'),
    SectorTile(key='XLV',  name='Health Care',             changePct=-0.22, status='CAUTION'),
    SectorTile(key='XLB',  name='Materials',               changePct=-0.41, status='REJECT'),
    SectorTile(key='XLRE', name='Real Estate',             changePct=-0.68, status='REJECT'),
    SectorTile(key='XLU',  name='Utilities',               changePct=-0.94, status='REJECT'),
    SectorTile(key='XLE',  name='Energy',                  changePct=-1.18, status='REJECT'),
]
