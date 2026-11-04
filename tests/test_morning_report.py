"""Guards for exact endpoints, data integrity and calendar boundaries."""
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from morning_report import series, since, relative_stats, risk_stats, build
from nyse_sessions import last_completed_session


@pytest.mark.parametrize('now,expected',[
    ('2026-11-01T01:00:00+00:00','2026-10-30'),
    ('2027-01-01T01:00:00+00:00','2026-12-31'),
])
def test_calendar_boundaries(now,expected):
    assert str(last_completed_session(datetime.fromisoformat(now))) == expected


def test_missing_benchmark_day_is_not_forward_filled():
    s=series(['2026-10-28','2026-10-29','2026-10-30'],[1,1.02,1.01])
    assert relative_stats(s,s.drop(s.index[1])) is None


@pytest.mark.parametrize('dates,values',[
    (['2026-10-30','2026-10-30'],[1,2]),
    (['2026-10-29','2026-10-30'],[1,float('nan')]),
    (['2026-10-29','2026-10-30'],[1,0]),
])
def test_invalid_curve_rejected(dates,values):
    with pytest.raises(ValueError): series(dates,values)


def test_sortino_uses_all_observations_and_cash():
    s=series(['2026-10-26','2026-10-27','2026-10-28','2026-10-29'],[1,1.02,1.0098,1.040094])
    cash=pd.Series(1.,index=s.index)
    r=s.pct_change().dropna()
    expected=r.mean()/np.sqrt(np.mean(np.minimum(r,0)**2))*np.sqrt(252)
    assert risk_stats(s,cash)['sortino']==pytest.approx(expected)


def test_period_anchor_requires_prior_observation():
    s=series(['2026-12-31','2027-01-04'],[1,1.02])
    assert since(s,pd.Timestamp('2026-12-31'))==pytest.approx(.02)
    assert since(s,pd.Timestamp('2026-12-30')) is None


def test_one_session_live_tail_is_valid():
    assert len(series(['2026-11-03'],[1.01],minimum=1)) == 1


def test_future_nav_is_rejected():
    d={'meta':{'live_asOf':'2026-11-04'},'equity':{
        'dates':['2026-11-03','2026-11-04'],'model':[1,1.01]}}
    with pytest.raises(ValueError,match='uncompleted'):
        build(d,datetime(2026,11,4,1,tzinfo=timezone.utc))
