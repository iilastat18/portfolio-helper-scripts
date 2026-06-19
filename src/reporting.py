from __future__ import annotations

from pathlib import Path

from src.rebalance import RebalanceResult


def write_markdown_report(result: RebalanceResult, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    top_orders = result.orders.head(8).copy()
    top_names = result.summary.sort_values("post_weight", ascending=False).head(8).copy()

    lines = [
        "# Portfolio Rebalance Report",
        "",
        "## Portfolio Snapshot",
        "",
        f"- Portfolio market value: `${result.portfolio_value:,.0f}`",
        f"- Gross turnover: `${result.gross_turnover:,.0f}`",
        f"- Configured cash buffer: `{result.target_cash_weight:.1%}`",
        "",
        "## Top Orders",
        "",
    ]

    if top_orders.empty:
        lines.extend(["No trades were required.", ""])
    else:
        lines.extend(
            [
                "| Symbol | Side | Shares | Trade Value | Note |",
                "| --- | --- | ---: | ---: | --- |",
            ]
        )
        for row in top_orders.itertuples(index=False):
            lines.append(
                f"| {row.symbol} | {row.side} | {int(row.trade_shares):,} | ${abs(float(row.trade_value)):,.0f} | {row.trade_note} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Post-Trade Concentration",
            "",
            "| Symbol | Post Weight | Target Weight | Weight Gap (bps) |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in top_names.itertuples(index=False):
        lines.append(
            f"| {row.symbol} | {float(row.post_weight):.2%} | {float(row.target_weight):.2%} | {float(row.weight_gap_bps):.1f} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Regional View",
            "",
            "| Region | Current Weight | Target Weight | Post Weight | Gap (bps) |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in result.region_view.itertuples(index=False):
        lines.append(
            f"| {row.region} | {float(row.current_weight):.2%} | {float(row.target_weight):.2%} | {float(row.post_weight):.2%} | {float(row.post_gap_bps):.1f} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Constraint Checks",
            "",
            "| Check | Status | Value | Limit | Comment |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for row in result.checks.itertuples(index=False):
        lines.append(
            f"| {row.check} | {row.status} | {float(row.value):.4f} | {float(row.limit):.4f} | {row.comment} |"
        )
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
