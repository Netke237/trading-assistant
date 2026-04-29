from app.schemas import UpcomingEvent

MOCK_EVENTS: list[UpcomingEvent] = [
    UpcomingEvent(date='2026-04-20', symbol='TSLA',  label='Earnings',           status='REJECT'),
    UpcomingEvent(date='2026-04-21', symbol='NVDA',  label='Earnings',           status='CAUTION'),
    UpcomingEvent(date='2026-04-23', symbol='\u2014',     label='FOMC',               status='CAUTION'),
    UpcomingEvent(date='2026-04-28', symbol='AAPL',  label='Earnings',           status='CAUTION'),
    UpcomingEvent(date='2026-04-29', symbol='META',  label='Earnings',           status='PASS'),
    UpcomingEvent(date='2026-04-30', symbol='MSFT',  label='Earnings',           status='CAUTION'),
    # May 2026
    UpcomingEvent(date='2026-05-01', symbol='AMZN',  label='Earnings',           status='PASS'),
    UpcomingEvent(date='2026-05-06', symbol='\u2014',     label='ISM Services PMI',   status='PASS'),
    UpcomingEvent(date='2026-05-14', symbol='\u2014',     label='CPI release',        status='CAUTION'),
    UpcomingEvent(date='2026-05-15', symbol='\u2014',     label='Monthly expiration', status='CAUTION'),
    UpcomingEvent(date='2026-05-21', symbol='NVDA',  label='Earnings (Q1)',      status='REJECT'),
    UpcomingEvent(date='2026-05-28', symbol='CRM',   label='Earnings',           status='CAUTION'),
    # June 2026
    UpcomingEvent(date='2026-06-04', symbol='\u2014',     label='ECB rate decision',  status='PASS'),
    UpcomingEvent(date='2026-06-11', symbol='\u2014',     label='CPI release',        status='CAUTION'),
    UpcomingEvent(date='2026-06-17', symbol='\u2014',     label='FOMC + dot plot',    status='REJECT'),
    UpcomingEvent(date='2026-06-19', symbol='\u2014',     label='Triple witching',    status='CAUTION'),
    UpcomingEvent(date='2026-06-25', symbol='NKE',   label='Earnings',           status='PASS'),
    UpcomingEvent(date='2026-06-30', symbol='MU',    label='Earnings',           status='CAUTION'),
    # July 2026
    UpcomingEvent(date='2026-07-02', symbol='\u2014',     label='NFP jobs report',    status='CAUTION'),
    UpcomingEvent(date='2026-07-14', symbol='JPM',   label='Earnings',           status='PASS'),
    UpcomingEvent(date='2026-07-15', symbol='\u2014',     label='CPI release',        status='CAUTION'),
    UpcomingEvent(date='2026-07-17', symbol='\u2014',     label='Monthly expiration', status='CAUTION'),
    UpcomingEvent(date='2026-07-22', symbol='TSLA',  label='Earnings',           status='REJECT'),
    UpcomingEvent(date='2026-07-23', symbol='GOOGL', label='Earnings',           status='CAUTION'),
    UpcomingEvent(date='2026-07-29', symbol='\u2014',     label='FOMC',               status='REJECT'),
    UpcomingEvent(date='2026-07-30', symbol='AAPL',  label='Earnings',           status='CAUTION'),
    UpcomingEvent(date='2026-07-30', symbol='AMZN',  label='Earnings',           status='CAUTION'),
    UpcomingEvent(date='2026-07-31', symbol='XOM',   label='Earnings',           status='PASS'),
    # August 2026
    UpcomingEvent(date='2026-08-06', symbol='\u2014',     label='BoE rate decision',  status='PASS'),
    UpcomingEvent(date='2026-08-12', symbol='\u2014',     label='CPI release',        status='CAUTION'),
    UpcomingEvent(date='2026-08-21', symbol='\u2014',     label='Monthly expiration', status='CAUTION'),
    UpcomingEvent(date='2026-08-27', symbol='NVDA',  label='Earnings (Q2)',      status='REJECT'),
    UpcomingEvent(date='2026-08-28', symbol='\u2014',     label='Jackson Hole close', status='CAUTION'),
    # September 2026
    UpcomingEvent(date='2026-09-04', symbol='\u2014',     label='NFP jobs report',    status='CAUTION'),
    UpcomingEvent(date='2026-09-10', symbol='\u2014',     label='ECB rate decision',  status='PASS'),
    UpcomingEvent(date='2026-09-11', symbol='\u2014',     label='CPI release',        status='CAUTION'),
    UpcomingEvent(date='2026-09-16', symbol='\u2014',     label='FOMC + projections', status='REJECT'),
    UpcomingEvent(date='2026-09-18', symbol='\u2014',     label='Triple witching',    status='CAUTION'),
    UpcomingEvent(date='2026-09-24', symbol='COST',  label='Earnings',           status='PASS'),
]
