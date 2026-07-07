import io
from datetime import datetime, timedelta, timezone

import pytest
import synth_data
from rich.console import Console

from llm_spend.report import render
from tests.conftest import make_record


def test_build_report_reconciles_our_total_by_construction():
    records = synth_data.generate_team(seed=1, days=60)
    data = render.build_report(records)
    assert data.reconciliation.our_total == data.total_cost
    assert data.reconciliation.provider_total is None
    assert data.reconciliation.flagged is False


def test_build_report_flags_divergence_over_1_percent():
    records = synth_data.generate_personal(seed=0, days=60)
    total = render.build_report(records).total_cost
    data = render.build_report(records, provider_total=total * 1.05)  # 5% off
    assert data.reconciliation.flagged is True
    assert data.reconciliation.divergence_pct == pytest.approx(0.05 / 1.05, rel=1e-3)


def test_build_report_does_not_flag_divergence_under_1_percent():
    records = synth_data.generate_personal(seed=0, days=60)
    total = render.build_report(records).total_cost
    data = render.build_report(records, provider_total=total * 1.005)  # 0.5% off
    assert data.reconciliation.flagged is False


def test_build_report_handles_short_history_gracefully():
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    records = [make_record(bucket_ts=start + timedelta(days=i), cost_usd=1.0) for i in range(5)]
    data = render.build_report(records)
    assert data.anomalies.insufficient_history is True
    assert data.overspend is not None
    assert data.forecast is not None


def test_build_report_handles_empty_records():
    data = render.build_report([])
    assert data.total_cost == 0
    assert data.most_expensive_day is None
    assert data.forecast is None
    assert data.overspend is None
    assert data.anomalies.insufficient_history is True


def _capture_terminal(data) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    render.render_terminal(data, console=console)
    return buffer.getvalue()


def test_render_terminal_smoke_on_team_scale():
    records = synth_data.generate_team(seed=1, days=60)
    data = render.build_report(records)
    output = _capture_terminal(data)

    assert "Total spend" in output
    assert "Most expensive day" in output
    assert "rough estimate" in output.lower()
    assert "hard spending cap" in output


def test_render_terminal_smoke_on_empty_report():
    data = render.build_report([])
    output = _capture_terminal(data)
    assert "Total spend" in output


def test_render_html_is_self_contained_with_no_external_assets():
    records = synth_data.generate_personal(seed=0, days=60)
    data = render.build_report(records)
    output = render.render_html(data)

    assert "<!doctype html>" in output.lower()
    assert "<title>llm-spend report</title>" in output
    assert "http://" not in output
    assert "https://" not in output
    assert "<link" not in output  # no external stylesheet
    assert "src=" not in output  # no external script/image
    assert "rough estimate" in output.lower()
    assert "hard spending cap" in output


def test_render_html_flags_reconciliation_divergence_visibly():
    records = synth_data.generate_team(seed=1, days=60)
    total = render.build_report(records).total_cost
    data = render.build_report(records, provider_total=total * 1.05)
    output = render.render_html(data)
    assert 'class="reconciliation flagged"' in output
    assert "diverges" in output.lower()


def test_render_html_batch_gap_uses_heuristic_language():
    records = synth_data.generate_team(seed=1, days=60)
    data = render.build_report(records)
    output = render.render_html(data)
    if data.batch_gap:
        assert "heuristic" in output.lower()
        assert "doesn't need to be real-time" in output
