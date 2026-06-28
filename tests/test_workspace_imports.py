from trade_analytics import PACKAGE_NAME as trade_analytics_name
from trade_brokers import PACKAGE_NAME as trade_brokers_name
from trade_core import PACKAGE_NAME as trade_core_name
from trade_data import PACKAGE_NAME as trade_data_name
from trade_execution_app import PACKAGE_NAME as trade_execution_app_name
from trade_reconcile_app import PACKAGE_NAME as trade_reconcile_app_name
from trade_research_app import PACKAGE_NAME as trade_research_app_name
from trade_strategies import PACKAGE_NAME as trade_strategies_name


def test_workspace_packages_are_importable() -> None:
    assert trade_core_name == "trade_core"
    assert trade_data_name == "trade_data"
    assert trade_strategies_name == "trade_strategies"
    assert trade_analytics_name == "trade_analytics"
    assert trade_brokers_name == "trade_brokers"
    assert trade_research_app_name == "trade_research_app"
    assert trade_execution_app_name == "trade_execution_app"
    assert trade_reconcile_app_name == "trade_reconcile_app"
