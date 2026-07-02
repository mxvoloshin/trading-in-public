from trade_analytics import PACKAGE_NAME as trade_analytics_name
from trade_brokers import PACKAGE_NAME as trade_brokers_name
from trade_core import PACKAGE_NAME as trade_core_name
from trade_data import PACKAGE_NAME as trade_data_name
from trade_execution_app import PACKAGE_NAME as trade_execution_app_name
from trade_reconcile_app import PACKAGE_NAME as trade_reconcile_app_name
from trade_research_app import PACKAGE_NAME as trade_research_app_name
from trade_research_app.vbt import run_vbt_backtest as _vbt_cli_run
from trade_strategies import PACKAGE_NAME as trade_strategies_name
from trade_vectorbt import PACKAGE_NAME as trade_vectorbt_name
from trade_vectorbt import Signals as _vbt_signals
from trade_vectorbt import VectorbtResult as _vbt_result
from trade_vectorbt import VectorbtSummary as _vbt_summary
from trade_vectorbt import build_vectorbt_summary as _vbt_build_summary
from trade_vectorbt import ma_cross_signals as _vbt_ma_cross
from trade_vectorbt import orb_signals as _vbt_orb
from trade_vectorbt import run_vectorbt_backtest as _vbt_run


def test_workspace_packages_are_importable() -> None:
    assert trade_core_name == "trade_core"
    assert trade_data_name == "trade_data"
    assert trade_strategies_name == "trade_strategies"
    assert trade_analytics_name == "trade_analytics"
    assert trade_brokers_name == "trade_brokers"
    assert trade_research_app_name == "trade_research_app"
    assert trade_execution_app_name == "trade_execution_app"
    assert trade_reconcile_app_name == "trade_reconcile_app"
    assert trade_vectorbt_name == "trade_vectorbt"
    # Phase 2 public API is importable from the top-level package.
    assert _vbt_signals is not None
    assert _vbt_result is not None
    assert callable(_vbt_ma_cross)
    assert callable(_vbt_run)
    # Phase 3 public API is importable.
    assert _vbt_summary is not None
    assert callable(_vbt_build_summary)
    # Phase 4: the CLI runner is importable from the research app's vbt package.
    assert callable(_vbt_cli_run)
    # ORB signal generator is importable.
    assert callable(_vbt_orb)
