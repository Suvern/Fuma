from app.cli.export_openapi import (
    DEFAULT_OUTPUT,
    check_implementation,
    load_schema,
    operations,
    render_schema,
)


def test_checked_in_json_matches_authoritative_yaml():
    assert DEFAULT_OUTPUT.read_text(encoding="utf-8") == render_schema()


def test_implemented_operations_are_a_subset_of_design():
    # Full coverage is a separate explicit M1 release gate, not proof supplied by this subset test.
    assert check_implementation(require_complete=False) == []


def test_all_cookie_writes_require_csrf_and_ci_uses_its_own_bearer():
    schema = load_schema()
    for (_, method), operation in operations(schema).items():
        access = operation.get("x-access", "public")
        if method not in {"get", "head", "options"} and access not in {"ci", "public"}:
            assert {"$ref": "#/components/parameters/CSRF"} in operation["parameters"]
        if access == "ci":
            assert operation["security"] == [{"ActionsToken": []}]


def test_frontend_dtos_exclude_provider_secrets_and_admin_tasks():
    schemas = load_schema()["components"]["schemas"]
    for name in ("CatalogApp", "CatalogEntry", "Preparation", "DownloadGrant"):
        properties = schemas[name]["properties"]
        assert not {"token", "app_secret", "repository_full_name", "task_id", "source"} & set(
            properties
        )
    assert "download_url" in schemas["DownloadGrant"]["properties"]
    assert "download_url" not in schemas["Preparation"]["properties"]
