from carnival.envsubst import expand_env, expand_env_if_set, expand_env_int_if_set


def test_expand(monkeypatch):
    monkeypatch.setenv("TEST_VAR", "test_value")
    monkeypatch.setenv("NAME", "world")
    monkeypatch.delenv("MISSING_VAR", raising=False)
    monkeypatch.setenv("PRESENT_VAR", "actual_value")
    monkeypatch.delenv("CARNIVAL_SERVICE_NAME", raising=False)

    assert expand_env("${TEST_VAR}") == "test_value"
    assert expand_env("$TEST_VAR") == "test_value"
    assert expand_env("${TEST_VAR}_$NAME") == "test_value_world"
    assert expand_env("Hello ${NAME}!") == "Hello world!"

    assert expand_env("${MISSING_VAR:-default_value}") == "default_value"
    assert expand_env("$MISSING_VAR") == "$MISSING_VAR"
    assert expand_env("${MISSING_VAR}") == "${MISSING_VAR}"
    assert expand_env("${PRESENT_VAR:-default_value}") == "actual_value"
    assert expand_env("${TEST_VAR}_${UNDEFINED}") == "test_value_${UNDEFINED}"
    assert expand_env(42) == "42"
    assert expand_env("${MISSING_VAR:-}") == ""
    assert expand_env("${MISSING_VAR:-/path/to/file}") == "/path/to/file"
    assert expand_env("Service: $CARNIVAL_SERVICE_NAME") == "Service: $CARNIVAL_SERVICE_NAME"


def test_expand_int_value(monkeypatch):
    monkeypatch.setenv("NUM", "123")
    monkeypatch.delenv("MISSING", raising=False)
    assert expand_env_int_if_set(42) == 42
    assert expand_env_int_if_set("${NUM}") == 123
    assert expand_env_int_if_set(None) is None
    assert expand_env_int_if_set("${MISSING:-999}") == 999


def test_expand_string_value(monkeypatch):
    """Test with string value."""
    monkeypatch.setenv("VAR", "value")
    monkeypatch.delenv("MISSING", raising=False)
    assert expand_env_if_set("${VAR}") == "value"
    assert expand_env_if_set(None) is None
    assert expand_env_if_set("${MISSING:-default}") == "default"
