from datetime import timedelta
from unittest.mock import Mock

import pytest

from highway_circutbreaker.circuit_breaker import CircuitBreakerPolicy, State
from highway_circutbreaker.exceptions import CircuitBreakerOpenError, RetriesExceeded
from highway_circutbreaker.failsafe import Failsafe
from highway_circutbreaker.retry import RetryPolicy


class TestFailsafe:
    @pytest.fixture
    def breaker(self):
        yield CircuitBreakerPolicy(cooldown=timedelta(milliseconds=10))

    @pytest.fixture
    def retry(self):
        yield RetryPolicy(max_retries=3)

    def test_should_construct_failsafe(self, breaker, retry):
        # given
        policies = (breaker, retry)

        # when
        failsafe = Failsafe(policies=policies)

        # then
        assert failsafe.policies is policies

    def test_should_require_unique_policies(self, retry):
        # given
        policies = (retry, retry)

        # when / then
        with pytest.raises(ValueError, match="All policies must be unique."):
            Failsafe(policies=policies)

    def test_should_return_original_method_when_no_policies_supplied(self):
        # given
        method = Mock()
        failsafe = Failsafe(policies=[])

        # when
        failsafe_method = failsafe(method)

        # then
        assert failsafe_method is method

    def test_should_wrap_original_method(self, breaker, retry):
        # given
        method = Mock()
        failsafe = Failsafe(policies=(retry, breaker))

        # when
        result = failsafe(method)()

        # then
        assert method.call_count == 1
        assert result is method.return_value

    def test_should_evaluate_retry_first(self, retry, breaker):
        # given
        method = Mock(side_effect=[RuntimeError, RuntimeError, "success"])
        failsafe = Failsafe(policies=(breaker, retry))
        failsafe_method = failsafe(method)

        # when
        result = failsafe_method()

        # then
        assert result == "success"
        assert method.call_count == 3
        assert breaker.state is State.CLOSED

    def test_should_evaluate_circuit_breaker_first(self, retry, breaker):
        # given
        method = Mock(side_effect=RuntimeError)
        failsafe = Failsafe(policies=(retry, breaker))
        failsafe_method = failsafe(method)

        # when
        with pytest.raises(RetriesExceeded) as e:
            failsafe_method()

        # then
        assert isinstance(e.value.__cause__, CircuitBreakerOpenError)
        assert method.call_count == 1
        assert breaker.state is State.OPEN
