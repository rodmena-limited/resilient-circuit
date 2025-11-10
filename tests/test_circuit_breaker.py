from contextlib import suppress
from datetime import timedelta
from fractions import Fraction
from time import sleep
from unittest.mock import Mock, call

import pytest

from highway_circutbreaker.circuit_breaker import CircuitBreakerPolicy, State
from highway_circutbreaker.exceptions import CircuitBreakerOpenError


class TestCircuitBreaker:
    @pytest.fixture
    def breaker(self):
        yield CircuitBreakerPolicy(cooldown=timedelta(milliseconds=50))

    def test_should_construct_policy_with_defaults(self):
        # given
        breaker = CircuitBreakerPolicy()

        # then
        assert breaker.cooldown == timedelta(0)
        assert breaker.failure_threshold == Fraction(1, 1)
        assert breaker.success_threshold == Fraction(1, 1)

    def test_should_return_result_when_execution_successful(self, breaker):
        # given
        method = Mock(return_value="test")

        # when
        result = breaker(method)()

        # then
        assert result == "test"

    def test_should_open_and_propagate_error_when_execution_fails(self, breaker):
        # given
        method = Mock(side_effect=RuntimeError)

        # when
        with pytest.raises(RuntimeError):
            breaker(method)()

        # then
        assert breaker.state is State.OPEN

    def test_should_stay_open_and_not_execute_until_cooldown_period_lapses(
        self, breaker
    ):
        # given
        method = Mock()
        breaker.state = State.OPEN

        # when / then
        with pytest.raises(CircuitBreakerOpenError):
            breaker(method)()
        assert method.call_count == 0

    def test_should_become_half_open_after_cooldown_period_lapses(self, breaker):
        # given
        method = Mock()
        breaker.state = State.OPEN

        # when
        sleep(0.06)
        breaker(method)()

        # then
        assert breaker.state is State.HALF_OPEN

    def test_should_stay_open_if_fails_after_cooldown_period_lapses(self, breaker):
        # given
        method = Mock(side_effect=RuntimeError)
        breaker.state = State.OPEN

        # when
        sleep(0.06)
        with pytest.raises(RuntimeError):
            breaker(method)()

        # then
        assert breaker.state is State.OPEN

    def test_should_open_when_fails_under_half_open_state(self, breaker):
        # given
        method = Mock(side_effect=RuntimeError)
        breaker.state = State.HALF_OPEN

        # when
        with pytest.raises(RuntimeError):
            breaker(method)()

        # then
        assert breaker.state is State.OPEN
        assert method.call_count == 1

    def test_should_close_when_succeeds_under_half_open_state(self, breaker):
        # given
        method = Mock()
        breaker.state = State.HALF_OPEN

        # when
        breaker(method)()

        # then
        assert breaker.state is State.CLOSED

    def test_should_provide_history_of_executions(self, breaker):
        # given
        method = Mock()

        # when
        breaker(method)()

        # then
        assert breaker.history.successes == 1
        assert breaker.history.failures == 0

    def test_should_keep_history_of_previous_execution_when_is_open(self, breaker):
        # given
        method = Mock(side_effect=RuntimeError)

        # when
        for _ in range(2):
            with suppress(Exception):
                breaker(method)()

        # then
        assert breaker.state is State.OPEN
        assert breaker.history.successes == 0
        assert breaker.history.failures == 1

    # noinspection PyTypeChecker
    def test_should_invoke_on_state_change_when_state_is_changed(self, breaker):
        # given
        state_change_callback = Mock()
        breaker = CircuitBreakerPolicy(on_state_change=state_change_callback)

        # when
        breaker.state = State.OPEN
        breaker.state = State.HALF_OPEN

        # then
        assert state_change_callback.call_count == 2
        state_change_callback.assert_has_calls(
            [
                call(breaker, State.CLOSED, State.OPEN),
                call(breaker, State.OPEN, State.HALF_OPEN),
            ]
        )


class TestCircuitBreakerWithThresholds:
    def test_should_open_after_reaching_failure_threshold(self):
        # given
        breaker = CircuitBreakerPolicy(failure_threshold=Fraction(2, 5))
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
            breaker(Mock())()

        # when
        for _ in range(8):
            with suppress(RuntimeError):
                breaker(method)()

        # then
        assert breaker.state is State.OPEN
        assert method.call_count == 8

    def test_should_stay_closed_before_reaching_failure_threshold(self):
        # given
        breaker = CircuitBreakerPolicy(failure_threshold=Fraction(3, 5))
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
            breaker(Mock())()

        # when
        for _ in range(8):
            with suppress(RuntimeError):
                breaker(method)()

        # then
        assert breaker.state is State.CLOSED
        assert method.call_count == 8

    def test_should_close_after_reaching_success_threshold(self):
        # given
        breaker = CircuitBreakerPolicy(
            success_threshold=Fraction(3, 5),
            failure_threshold=Fraction(2, 10),
        )
        breaker.state = State.HALF_OPEN
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
                breaker(method)()

        # then
        assert breaker.state is State.CLOSED

    def test_should_open_according_to_failure_threshold_when_success_threshold_not_set(
        self,
    ):
        # given
        breaker = CircuitBreakerPolicy(failure_threshold=Fraction(2, 5))
        breaker.state = State.HALF_OPEN
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
                breaker(method)()

        # then
        assert breaker.state is State.OPEN

    def test_should_stay_open_until_reaching_success_threshold(self):
        # given
        breaker = CircuitBreakerPolicy(success_threshold=Fraction(4, 5))
        breaker.state = State.OPEN
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
            with suppress(RuntimeError):
                breaker(method)()

        # then
        assert breaker.state is State.OPEN


class TestCircuitBreakerWithExceptionHandling:
    def test_should_open_when_exception_must_be_handled(self):
        # given
        breaker = CircuitBreakerPolicy(handle=lambda e: isinstance(e, ValueError))
        method = Mock(side_effect=ValueError)

        # when
        with pytest.raises(ValueError):
            breaker(method)()

        # then
        assert breaker.state is State.OPEN

    def test_should_stay_closed_when_exception_must_not_be_handled(self):
        # given
        breaker = CircuitBreakerPolicy(handle=lambda e: isinstance(e, RuntimeError))
        method = Mock(side_effect=ValueError)

        # when
        with pytest.raises(ValueError):
            breaker(method)()

        # then
        assert breaker.state is State.CLOSED
