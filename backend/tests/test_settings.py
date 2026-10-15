from backend.app.config.settings import Settings


def test_optional_settings_defaults_do_not_require_secrets_or_database() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url is None
    assert settings.llm_provider is None
    assert settings.tavily_api_key is None
    assert settings.max_steps > 0


def test_comma_separated_origins_and_official_domains_are_parsed() -> None:
    settings = Settings(
        _env_file=None,
        CORS_ORIGINS="http://localhost:5173,https://ui.example.invalid",
        OFFICIAL_DOMAINS="rbi.org.in, sebi.gov.in",
    )

    assert settings.cors_origins == [
        "http://localhost:5173",
        "https://ui.example.invalid",
    ]
    assert settings.official_domains == ["rbi.org.in", "sebi.gov.in"]


def test_environment_values_are_parsed_without_a_json_array(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173,https://ui.example.invalid")
    monkeypatch.setenv("OFFICIAL_DOMAINS", "rbi.org.in,sebi.gov.in")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == [
        "http://localhost:5173",
        "https://ui.example.invalid",
    ]
    assert settings.official_domains == ["rbi.org.in", "sebi.gov.in"]
