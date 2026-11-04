"""Protect quantitative bar encodings from silently misleading comparisons."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from render_morning import BarValue, GREEN, RED, bar_html, return_scale


def test_positive_negative_use_symmetric_magnitude_scale():
    gain,loss=BarValue(.1,.2),BarValue(-.1,.2)
    assert gain.fraction == loss.fraction == .5
    assert gain.colour==GREEN and loss.colour==RED
    assert '+10.00%' in bar_html(gain) and '-10.00%' in bar_html(loss)


def test_missing_value_is_not_rendered_as_zero_bar():
    assert 'height:4px' not in bar_html(BarValue(None,1,label='-'))
    assert 'height:4px' in bar_html(BarValue(0,1))


def test_scale_includes_benchmarks_and_both_signs():
    assert return_scale({'performance':[{'model':.1,'SPY':-.3,'AOR':.2}]})==.3
    with pytest.raises(ValueError,match='complete observation'):
        _=BarValue(.4,.3).fraction
