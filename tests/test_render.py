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


def _capture_terminal(data, share: bool = False) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    render.render_terminal(data, console=console, share=share)
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
        assert "cache interactions" in output.lower()  # html.escape turns "aren't" into an entity


def _multi_tier_records():
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return [
        make_record(bucket_ts=start, model="m", service_tier="standard", input_tokens=1000, output_tokens=0, cost_usd=2.0),
        make_record(bucket_ts=start, model="m", service_tier="priority", input_tokens=1000, output_tokens=0, cost_usd=4.0),
    ]


def test_render_terminal_shows_service_tier_gap_with_caveat():
    data = render.build_report(_multi_tier_records())
    assert data.service_tier_gap  # sanity: the fixture actually produces a comparison
    output = _capture_terminal(data)
    assert "Service tier cost per 1K tokens" in output
    assert "output token share" in output.lower()
    assert "blends input and output tokens" in output


def test_render_html_shows_service_tier_gap_with_caveat():
    data = render.build_report(_multi_tier_records())
    output = render.render_html(data)
    assert "Service tier cost per 1K tokens" in output
    assert "output token share" in output.lower()
    assert "blends input and output tokens" in output


def test_render_terminal_share_mode_has_no_dollar_amounts():
    records = synth_data.generate_team(seed=1, days=60)
    data = render.build_report(records)
    output = _capture_terminal(data, share=True)
    assert "$" not in output


def test_render_html_share_mode_has_no_dollar_amounts():
    records = synth_data.generate_team(seed=1, days=60)
    data = render.build_report(records)
    output = render.render_html(data, share=True)
    assert "$" not in output


def test_render_share_mode_masks_real_api_key_and_project_names():
    records = synth_data.generate_team(seed=1, days=60)
    data = render.build_report(records)
    real_keys = [row.value for row in data.by_api_key if row.value != "(none)"]
    real_projects = [row.value for row in data.by_project if row.value != "(none)"]
    assert real_keys and real_projects  # sanity: synthetic team data actually has these

    terminal_output = _capture_terminal(data, share=True)
    html_output = render.render_html(data, share=True)

    for real_value in real_keys + real_projects:
        assert real_value not in terminal_output
        assert real_value not in html_output

    assert "key-1" in terminal_output
    assert "project-1" in terminal_output
    assert "key-1" in html_output
    assert "project-1" in html_output


def test_render_share_mode_omits_forecast_overspend_and_reconciliation():
    records = synth_data.generate_team(seed=1, days=60)
    data = render.build_report(records)

    terminal_output = _capture_terminal(data, share=True)
    html_output = render.render_html(data, share=True)

    for output in (terminal_output, html_output):
        assert "Forecast" not in output
        assert "Overspend scenario" not in output
        assert "billing dashboard" not in output


def test_render_share_mode_keeps_model_names_unmasked():
    records = synth_data.generate_team(seed=1, days=60)
    data = render.build_report(records)
    real_model = data.by_model[0].value

    terminal_output = _capture_terminal(data, share=True)
    assert real_model in terminal_output


def test_render_share_mode_anomaly_shown_as_ratio_not_dollar_amount():
    records = _spike_records_for_share_test()
    data = render.build_report(records)
    assert data.anomalies.anomalies  # sanity: fixture actually produces a flagged anomaly

    output = _capture_terminal(data, share=True)
    assert "vs. typical" in output
    assert "x typical" in output


def _spike_records_for_share_test():
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    records = []
    for i in range(56):
        cost = 50.0 if i == 49 else 1.0
        records.append(make_record(bucket_ts=start + timedelta(days=i), cost_usd=cost))
    return records
