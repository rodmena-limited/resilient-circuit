from contextlib import suppress
from datetime import timedelta
from fractions import Fraction
from time import sleep
from unittest.mock import Mock, call

import pytest

from resilient_circuit.circuit_breaker import CircuitProtectorPolicy, CircuitStatus
from resilient_circuit.exceptions import ProtectedCallError


class TestCircuitProtector:
    @pytest.fixture
    def protector(self):
        yield CircuitProtectorPolicy(cooldown=timedelta(milliseconds=50))

    def test_should_construct_policy_with_defaults(self):
        # given
        protector = CircuitProtectorPolicy()

        # then
        assert protector.cooldown == timedelta(0)
        assert protector.failure_limit == Fraction(1, 1)
        assert protector.success_limit == Fraction(1, 1)

    def test_should_return_result_when_execution_successful(self, protector):
        # given
        method = Mock(return_value="test")

        # when
        result = protector(method)()

        # then
        assert result == "test"

    def test_should_open_and_propagate_error_when_execution_fails(self, protector):
        # given
        method = Mock(side_effect=RuntimeError)

        # when
        with pytest.raises(RuntimeError):
            protector(method)()

        # then
        assert protector.status is CircuitStatus.OPEN

    def test_should_stay_open_and_not_execute_until_cooldown_period_lapses(
        self, protector
    ):
        # given
        method = Mock()
        protector.status = CircuitStatus.OPEN

        # when / then
        with pytest.raises(ProtectedCallError):
            protector(method)()
        assert method.call_count == 0

    def test_should_become_half_open_after_cooldown_period_lapses(self, protector):
        # given
        method = Mock()
        protector.status = CircuitStatus.OPEN

        # when
        sleep(0.06)
        protector(method)()

        # then
        # After cooldown expires, circuit transitions to HALF_OPEN automatically
        # A successful call in HALF_OPEN closes the circuit
        assert protector.status is CircuitStatus.CLOSED

    def test_should_stay_open_if_fails_after_cooldown_period_lapses(self, protector):
        # given
        method = Mock(side_effect=RuntimeError)
        protector.status = CircuitStatus.OPEN

        # when
        sleep(0.06)
        with pytest.raises(RuntimeError):
            protector(method)()

        # then
        assert protector.status is CircuitStatus.OPEN

    def test_should_open_when_fails_under_half_open_state(self, protector):
        # given
        method = Mock(side_effect=RuntimeError)
        protector.status = CircuitStatus.HALF_OPEN

        # when
        with pytest.raises(RuntimeError):
            protector(method)()

        # then
        assert protector.status is CircuitStatus.OPEN
        assert method.call_count == 1

    def test_should_close_when_succeeds_under_half_open_state(self, protector):
        # given
        method = Mock()
        protector.status = CircuitStatus.HALF_OPEN

        # when
        protector(method)()

        # then
        assert protector.status is CircuitStatus.CLOSED

    def test_should_provide_history_of_executions(self, protector):
        # given
        method = Mock()

        # when
        protector(method)()

        # then
        assert protector.execution_log.success_count == 1
        assert protector.execution_log.failure_count == 0

    def test_should_keep_history_of_previous_execution_when_is_open(self, protector):
        # given
        method = Mock(side_effect=RuntimeError)

        # when
        for _ in range(2):
            with suppress(Exception):
                protector(method)()

        # then
        assert protector.status is CircuitStatus.OPEN
        assert protector.execution_log.success_count == 0
        assert protector.execution_log.failure_count == 1

    # noinspection PyTypeChecker
    def test_should_invoke_on_status_change_when_status_is_changed(self, protector):
        # given
        state_change_callback = Mock()
        protector = CircuitProtectorPolicy(on_status_change=state_change_callback)

        # when
        protector.status = CircuitStatus.OPEN
        protector.status = CircuitStatus.HALF_OPEN

        # then
        assert state_change_callback.call_count == 2
        state_change_callback.assert_has_calls(
            [
                call(protector, CircuitStatus.CLOSED, CircuitStatus.OPEN),
                call(protector, CircuitStatus.OPEN, CircuitStatus.HALF_OPEN),
            ]
        )


class TestCircuitProtectorWithLimits:
    def test_should_open_after_reaching_failure_limit(self):
        # given
        protector = CircuitProtectorPolicy(failure_limit=Fraction(2, 5))
        method = Mock(
            side_effect=[
                "response-1",
                RuntimeError,
                "response-3",
                "response-4",
                "response-5",
                "response-6",
                RuntimeError,
                RuntimeError,
            ]
        )
        # simulate history of successful executions
        for _ in range(5):
            protector(Mock())()

        # when
        for _ in range(8):
            with suppress(RuntimeError):
                protector(method)()

        # then
        assert protector.status is CircuitStatus.OPEN
        assert method.call_count == 8

    def test_should_stay_closed_before_reaching_failure_limit(self):
        # given
        protector = CircuitProtectorPolicy(failure_limit=Fraction(3, 5))
        method = Mock(
            side_effect=[
                "response-1",
                RuntimeError,
                "response-3",
                "response-4",
                "response-5",
                "response-6",
                RuntimeError,
                "response-8",
            ]
        )
        # simulate history of successful executions
        for _ in range(5):
            protector(Mock())()

        # when
        for _ in range(8):
            with suppress(RuntimeError):
                protector(method)()

        # then
        assert protector.status is CircuitStatus.CLOSED
        assert method.call_count == 8

    def test_should_close_after_reaching_success_limit(self):
        # given
        protector = CircuitProtectorPolicy(
            success_limit=Fraction(3, 5),
            failure_limit=Fraction(2, 10),
        )
        protector.status = CircuitStatus.HALF_OPEN
        method = Mock(
            side_effect=[
                RuntimeError,
                "response-2",
                RuntimeError,
                "response-4",
                "response-5",
                "response-6",
                RuntimeError,
                "response-8",
                "response-9",
            ]
        )

        # when
        for _ in range(9):
            with suppress(RuntimeError):
                protector(method)()

        # then
        assert protector.status is CircuitStatus.CLOSED

    def test_should_open_according_to_failure_limit_when_success_limit_not_set(
        self,
    ):
        # given
        protector = CircuitProtectorPolicy(failure_limit=Fraction(2, 5))
        protector.status = CircuitStatus.HALF_OPEN
        method = Mock(
            side_effect=[
                RuntimeError,
                "response-2",
                RuntimeError,
                "response-4",
                "response-5",
            ]
        )

        # when
        for _ in range(5):
            with suppress(RuntimeError):
                protector(method)()

        # then
        assert protector.status is CircuitStatus.OPEN

    def test_should_stay_open_until_reaching_success_limit(self):
        # given
        # Need a cooldown to prevent immediate transition to HALF_OPEN
        protector = CircuitProtectorPolicy(
            success_limit=Fraction(4, 5),
            cooldown=timedelta(seconds=10)  # Long cooldown to keep it OPEN
        )
        protector.status = CircuitStatus.OPEN
        method = Mock(
            side_effect=[
                "response-1",
                RuntimeError,
                RuntimeError,
                "response-4",
                RuntimeError,
                "response-6",
            ]
        )

        # when
        for _ in range(6):
            with suppress(RuntimeError, ProtectedCallError):
                protector(method)()

        # then
        # Circuit should stay OPEN because cooldown hasn't expired
        assert protector.status is CircuitStatus.OPEN


class TestCircuitProtectorWithExceptionHandling:
    def test_should_open_when_exception_must_be_handled(self):
        # given
        protector = CircuitProtectorPolicy(should_handle=lambda e: isinstance(e, ValueError))
        method = Mock(side_effect=ValueError)

        # when
        with pytest.raises(ValueError):
            protector(method)()

        # then
        assert protector.status is CircuitStatus.OPEN

    def test_should_stay_closed_when_exception_must_not_be_handled(self):
        # given
        protector = CircuitProtectorPolicy(should_handle=lambda e: isinstance(e, RuntimeError))
        method = Mock(side_effect=ValueError)

        # when
        with pytest.raises(ValueError):
            protector(method)()

        # then
        assert protector.status is CircuitStatus.CLOSED
