from llm_spend.pricing import load_pricing


def test_load_pricing_has_both_providers():
    pricing = load_pricing()
    assert "openai" in pricing
    assert "anthropic" in pricing


def test_load_pricing_models_have_required_fields():
    pricing = load_pricing()
    for provider, models in pricing.items():
        if provider == "as_of":
            continue
        for model, fields in models.items():
            assert "input" in fields, f"{provider}/{model} missing input price"
            assert "output" in fields, f"{provider}/{model} missing output price"
