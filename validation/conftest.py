"""Capture only fixture screenshots, never cookie-bearing browser traces."""
import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, 'report_' + report.when, report)


@pytest.fixture
def test_outcome(request):
    return request.node
