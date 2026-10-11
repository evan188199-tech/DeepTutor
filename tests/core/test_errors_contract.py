"""Contract tests for the core error envelope (deeptutor/core/errors.py).

Locks the backend error-value baseline: the exception hierarchy, the
carried fields (``message`` / ``details``), and the string/serialization
form every ``DeepTutorError`` subclass inherits.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.core.errors import (
    ConfigurationError,
    DeepTutorError,
    EnvironmentConfigError,
    LLMContextError,
    LLMServiceError,
    ServiceError,
    ValidationError,
)

ALL_ERRORS = [
    DeepTutorError,
    ConfigurationError,
    ValidationError,
    ServiceError,
    LLMServiceError,
    LLMContextError,
    EnvironmentConfigError,
]


# ---------------------------------------------------------------------------
# Error type contract
# ---------------------------------------------------------------------------


class TestErrorTypeContract:
    @pytest.mark.parametrize("error_cls", ALL_ERRORS, ids=lambda c: c.__name__)
    def test_every_error_is_an_exception(self, error_cls: type[DeepTutorError]) -> None:
        assert issubclass(error_cls, Exception)

    def test_direct_hierarchy(self) -> None:
        assert issubclass(ConfigurationError, DeepTutorError)
        assert issubclass(ValidationError, DeepTutorError)
        assert issubclass(ServiceError, DeepTutorError)
        assert issubclass(LLMServiceError, ServiceError)
        assert issubclass(LLMContextError, LLMServiceError)
        assert issubclass(EnvironmentConfigError, ConfigurationError)

    def test_hierarchy_is_transitive(self) -> None:
        assert issubclass(LLMContextError, ServiceError)
        assert issubclass(LLMContextError, DeepTutorError)
        assert issubclass(EnvironmentConfigError, DeepTutorError)
        assert issubclass(LLMServiceError, DeepTutorError)

    def test_every_error_is_catchable_as_deep_tutor_error(self) -> None:
        for error_cls in ALL_ERRORS:
            with pytest.raises(DeepTutorError):
                raise error_cls("boom")

    def test_sibling_branches_do_not_catch_each_other(self) -> None:
        """Configuration vs Service vs Validation branches stay discriminating."""
        with pytest.raises(DeepTutorError):
            try:
                raise ConfigurationError("bad config")
            except ServiceError:
                pytest.fail("ConfigurationError must not be caught as ServiceError")
            except ValidationError:
                pytest.fail("ConfigurationError must not be caught as ValidationError")
        with pytest.raises(DeepTutorError):
            try:
                raise ServiceError("bad service")
            except ConfigurationError:
                pytest.fail("ServiceError must not be caught as ConfigurationError")


# ---------------------------------------------------------------------------
# Envelope field contract
# ---------------------------------------------------------------------------


class TestErrorEnvelopeFields:
    @pytest.mark.parametrize("error_cls", ALL_ERRORS, ids=lambda c: c.__name__)
    def test_message_is_carried_verbatim(self, error_cls: type[DeepTutorError]) -> None:
        err = error_cls("something failed")
        assert err.message == "something failed"
        assert err.args == ("something failed",)

    @pytest.mark.parametrize("error_cls", ALL_ERRORS, ids=lambda c: c.__name__)
    def test_details_defaults_to_empty_dict(self, error_cls: type[DeepTutorError]) -> None:
        assert error_cls("boom").details == {}
        assert error_cls("boom", details=None).details == {}

    def test_details_are_carried(self) -> None:
        err = DeepTutorError("boom", details={"key": "val", "attempt": 2})
        assert err.details == {"key": "val", "attempt": 2}

    def test_details_default_is_independent_per_instance(self) -> None:
        first = DeepTutorError("first")
        second = DeepTutorError("second")
        first.details["leaked"] = True
        assert second.details == {}

    def test_empty_details_is_a_dict_not_none(self) -> None:
        assert isinstance(DeepTutorError("boom").details, dict)


# ---------------------------------------------------------------------------
# String / serialization form contract
# ---------------------------------------------------------------------------


class TestErrorStringContract:
    @pytest.mark.parametrize("error_cls", ALL_ERRORS, ids=lambda c: c.__name__)
    def test_str_is_the_bare_message_without_details(self, error_cls: type[DeepTutorError]) -> None:
        assert str(error_cls("boom")) == "boom"
        assert str(error_cls("boom", details={})) == "boom"

    def test_str_appends_details_block_when_details_present(self) -> None:
        err = DeepTutorError("boom", details={"key": "val"})
        assert str(err) == "boom (details: {'key': 'val'})"

    def test_details_survive_a_json_round_trip(self) -> None:
        err = DeepTutorError("boom", details={"model": "gpt", "retry": 1, "ok": True})
        assert json.loads(json.dumps(err.details)) == {"model": "gpt", "retry": 1, "ok": True}

    @pytest.mark.parametrize("error_cls", ALL_ERRORS[1:], ids=lambda c: c.__name__)
    def test_subclasses_inherit_the_envelope(self, error_cls: type[DeepTutorError]) -> None:
        err = error_cls("envelope held", details={"origin": "contract-test"})
        assert err.message == "envelope held"
        assert err.details == {"origin": "contract-test"}
        assert "envelope held" in str(err)
        assert "origin" in str(err)
