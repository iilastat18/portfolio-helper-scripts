from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


REQUIRED_POSITION_COLUMNS = {
    "symbol",
    "name",
    "region",
    "sector",
    "price",
    "shares",
    "round_lot",
}
REQUIRED_TARGET_COLUMNS = {"symbol", "target_weight"}


@dataclass(frozen=True)
class RebalanceResult:
    summary: pd.DataFrame
    orders: pd.DataFrame
    region_view: pd.DataFrame
    checks: pd.DataFrame
    portfolio_value: float
    gross_turnover: float
    target_cash_weight: float


def load_positions(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = REQUIRED_POSITION_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"Positions file is missing columns: {sorted(missing)}")
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    return frame


def load_targets(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = REQUIRED_TARGET_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"Targets file is missing columns: {sorted(missing)}")
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    return frame


def compute_rebalance(
    positions: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    cash_buffer_weight: float = 0.02,
    max_name_weight: float = 0.18,
    max_region_weight: float = 0.55,
) -> RebalanceResult:
    if not 0 <= cash_buffer_weight < 1:
        raise ValueError("cash_buffer_weight must be between 0 and 1.")

    frame = positions.merge(targets, on="symbol", how="left")
    frame["target_weight"] = frame["target_weight"].fillna(0.0)
    frame["current_value"] = frame["price"] * frame["shares"]

    portfolio_value = float(frame["current_value"].sum())
    investable_value = portfolio_value * (1 - cash_buffer_weight)
    frame["current_weight"] = (frame["current_value"] / portfolio_value).fillna(0.0)
    frame["target_value"] = frame["target_weight"] * investable_value
    frame["delta_value"] = frame["target_value"] - frame["current_value"]
    frame["raw_trade_shares"] = frame["delta_value"] / frame["price"]
    frame["trade_shares"] = frame.apply(_round_trade_shares, axis=1)
    frame["trade_value"] = (frame["trade_shares"] * frame["price"]).round(2)
    frame["post_shares"] = frame["shares"] + frame["trade_shares"]
    frame["post_value"] = (frame["post_shares"] * frame["price"]).round(2)
    frame["post_weight"] = (frame["post_value"] / portfolio_value).fillna(0.0)
    frame["weight_gap_bps"] = ((frame["post_weight"] - frame["target_weight"]) * 10_000).round(1)
    frame["side"] = frame["trade_shares"].map(_side_for_trade)
    frame["trade_note"] = frame.apply(_trade_note, axis=1)

    summary = frame.loc[
        :,
        [
            "symbol",
            "name",
            "region",
            "sector",
            "price",
            "shares",
            "current_weight",
            "target_weight",
            "trade_shares",
            "trade_value",
            "post_weight",
            "weight_gap_bps",
            "trade_note",
        ],
    ].copy()
    summary = summary.sort_values(["trade_value", "symbol"], ascending=[False, True]).reset_index(drop=True)

    orders = frame.loc[frame["trade_shares"] != 0, ["symbol", "name", "price", "trade_shares", "trade_value", "side", "trade_note"]].copy()
    orders["abs_trade_value"] = orders["trade_value"].abs()
    orders = orders.sort_values(["abs_trade_value", "symbol"], ascending=[False, True]).drop(columns="abs_trade_value").reset_index(drop=True)

    region_view = (
        frame.groupby("region", as_index=False)
        .agg(
            current_weight=("current_weight", "sum"),
            target_weight=("target_weight", "sum"),
            post_weight=("post_weight", "sum"),
            net_trade_value=("trade_value", "sum"),
        )
        .round(4)
    )
    region_view["post_gap_bps"] = ((region_view["post_weight"] - region_view["target_weight"]) * 10_000).round(1)

    gross_turnover = float(orders["trade_value"].abs().sum()) if not orders.empty else 0.0
    checks = build_checks(
        summary=summary,
        region_view=region_view,
        target_cash_weight=cash_buffer_weight,
        gross_turnover=gross_turnover / portfolio_value if portfolio_value else 0.0,
        max_name_weight=max_name_weight,
        max_region_weight=max_region_weight,
    )

    return RebalanceResult(
        summary=summary,
        orders=orders,
        region_view=region_view,
        checks=checks,
        portfolio_value=portfolio_value,
        gross_turnover=gross_turnover,
        target_cash_weight=cash_buffer_weight,
    )


def build_checks(
    *,
    summary: pd.DataFrame,
    region_view: pd.DataFrame,
    target_cash_weight: float,
    gross_turnover: float,
    max_name_weight: float,
    max_region_weight: float,
) -> pd.DataFrame:
    target_weight_sum = float(summary["target_weight"].sum())
    max_post_name = float(summary["post_weight"].max()) if not summary.empty else 0.0
    max_post_region = float(region_view["post_weight"].max()) if not region_view.empty else 0.0
    cash_ok = target_weight_sum <= (1 - target_cash_weight + 1e-6)

    rows = [
        {
            "check": "Target weights + cash buffer",
            "status": "PASS" if cash_ok else "FAIL",
            "value": round(target_weight_sum + target_cash_weight, 4),
            "limit": 1.0,
            "comment": "Target weights should leave room for the configured cash buffer.",
        },
        {
            "check": "Max single-name weight",
            "status": "PASS" if max_post_name <= max_name_weight else "FAIL",
            "value": round(max_post_name, 4),
            "limit": max_name_weight,
            "comment": "Largest post-trade name weight stays within concentration limit.",
        },
        {
            "check": "Max regional weight",
            "status": "PASS" if max_post_region <= max_region_weight else "FAIL",
            "value": round(max_post_region, 4),
            "limit": max_region_weight,
            "comment": "Largest regional allocation stays within the region cap.",
        },
        {
            "check": "Gross turnover",
            "status": "PASS" if gross_turnover <= 0.35 else "WARN",
            "value": round(gross_turnover, 4),
            "limit": 0.35,
            "comment": "Turnover above 35% is flagged as potentially expensive to execute.",
        },
    ]
    return pd.DataFrame(rows)


def export_outputs(result: RebalanceResult, output_dir: str | Path) -> tuple[Path, Path, Path, Path]:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    summary_path = path / "rebalance_summary.csv"
    orders_path = path / "orders.csv"
    region_path = path / "region_view.csv"
    checks_path = path / "checks.csv"

    result.summary.to_csv(summary_path, index=False)
    result.orders.to_csv(orders_path, index=False)
    result.region_view.to_csv(region_path, index=False)
    result.checks.to_csv(checks_path, index=False)
    return summary_path, orders_path, region_path, checks_path


def _round_trade_shares(row: pd.Series) -> int:
    lot = int(max(row["round_lot"], 1))
    raw = float(row["raw_trade_shares"])
    rounded = int(round(raw / lot) * lot)
    post = int(row["shares"]) + rounded
    if post < 0:
        rounded = -int(row["shares"])
    return int(rounded)


def _side_for_trade(trade_shares: int) -> str:
    if trade_shares > 0:
        return "BUY"
    if trade_shares < 0:
        return "SELL"
    return "HOLD"


def _trade_note(row: pd.Series) -> str:
    gap = float(row["weight_gap_bps"])
    if row["trade_shares"] == 0:
        return "No rebalance required."
    if abs(gap) <= 35:
        return "Rounded to lot size and close to target."
    if gap > 0:
        return "Still modestly overweight after lot rounding."
    return "Still modestly underweight after lot rounding."
