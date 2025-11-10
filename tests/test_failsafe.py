from datetime import timedelta
from unittest.mock import Mock

import pytest

from highway_circutbreaker.circuit_breaker import CircuitProtectorPolicy, CircuitStatus
from highway_circutbreaker.exceptions import ProtectedCallError, RetryLimitReached
from highway_circutbreaker.failsafe import SafetyNet
from highway_circutbreaker.retry import RetryWithBackoffPolicy


class TestSafetyNet:
    @pytest.fixture
    def protector(self):
        yield CircuitProtectorPolicy(cooldown=timedelta(milliseconds=10))

    @pytest.fixture
    def backoff_retries(self):
        yield RetryWithBackoffPolicy(max_retries=3)

    def test_should_construct_safety_net(self, protector, backoff_retries):
        # given
        policies = (protector, backoff_retries)

        # when
        safety_net = SafetyNet(policies=policies)

        # then
        assert safety_net.policies is policies

    def test_should_require_unique_policies(self, backoff_retries):
        # given
        policies = (backoff_retries, backoff_retries)

        # when / then
        with pytest.raises(ValueError, match="All policies must be unique."):
            SafetyNet(policies=policies)

    def test_should_return_original_method_when_no_policies_supplied(self):
        # given
        method = Mock()
        safety_net = SafetyNet(policies=[])

        # when
        safety_net_method = safety_net(method)

        # then
        assert safety_net_method is method

    def test_should_wrap_original_method(self, protector, backoff_retries):
        # given
        method = Mock()
        safety_net = SafetyNet(policies=(backoff_retries, protector))

        # when
        result = safety_net(method)()

        # then
        assert method.call_count == 1
        assert result is method.return_value

    def test_should_evaluate_retry_first(self, backoff_retries, protector):
        # given
        method = Mock(side_effect=[RuntimeError, RuntimeError, "success"])
        safety_net = SafetyNet(policies=(protector, backoff_retries))
        safety_net_method = safety_net(method)

        # when
        result = safety_net_method()

        # then
        assert result == "success"
        assert method.call_count == 3
        assert protector.status is CircuitStatus.CLOSED

    def test_should_evaluate_circuit_protector_first(self, backoff_retries, protector):
        # given
        method = Mock(side_effect=RuntimeError)
        safety_net = SafetyNet(policies=(backoff_retries, protector))
        safety_net_method = safety_net(method)

        # when
        with pytest.raises(RetryLimitReached) as e:
            safety_net_method()

        # then
        assert isinstance(e.value.__cause__, ProtectedCallError)
        assert method.call_count == 1
        assert protector.status is CircuitStatus.OPEN
