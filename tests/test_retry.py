from datetime import timedelta
from unittest.mock import Mock, call

import pytest

from highway_circutbreaker import retry as retry_module
from highway_circutbreaker.backoff import FixedDelay
from highway_circutbreaker.exceptions import RetryLimitReached
from highway_circutbreaker.retry import RetryWithBackoffPolicy


class TestRetryWithBackoffPolicy:
    def test_should_return_result_when_execution_successful(self):
        # given
        method = Mock(return_value="test")
        backoff_retries = RetryWithBackoffPolicy()

        # when
        result = backoff_retries(method)()

        # then
        assert result == "test"

    def test_should_retry_when_first_execution_fails(self):
        # given
        method = Mock(side_effect=[RuntimeError, "test"])
        backoff_retries = RetryWithBackoffPolicy()

        # when
        result = backoff_retries(method)()

        # then
        assert result == "test"
        assert method.call_count == 2

    def test_should_not_retry_beyond_max_retries(self):
        # given
        method = Mock(side_effect=RuntimeError)
        backoff_retries = RetryWithBackoffPolicy(max_retries=2)

        # when / then
        with pytest.raises(RetryLimitReached):
            backoff_retries(method)()

        assert method.call_count == 3

    def test_should_retry_with_delays_between_calls(self, mocker):
        # given
        mocked_sleep = mocker.patch.object(retry_module, "sleep")
        backoff_retries = RetryWithBackoffPolicy(backoff=FixedDelay(timedelta(seconds=1)))
        method = Mock(side_effect=[RuntimeError, RuntimeError, "test"])

        # when
        backoff_retries(method)()

        # then
        mocked_sleep.assert_has_calls([call(1.0), call(1.0)])

    def test_should_retry_when_exception_must_be_handled(self):
        # given
        backoff_retries = RetryWithBackoffPolicy(max_retries=3, should_handle=lambda e: isinstance(e, RuntimeError))
        method = Mock(side_effect=[RuntimeError, RuntimeError, "test"])

        # when
        result = backoff_retries(method)()

        # then
        assert result == "test"
        assert method.call_count == 3

    def test_should_abort_when_exception_must_not_be_handled(self):
        # given
        backoff_retries = RetryWithBackoffPolicy(max_retries=3, should_handle=lambda e: isinstance(e, RuntimeError))
        method = Mock(side_effect=ValueError)

        # when / then
        with pytest.raises(ValueError):
            backoff_retries(method)()

        assert method.call_count == 1
