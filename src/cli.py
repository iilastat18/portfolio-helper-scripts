from __future__ import annotations

import argparse
from pathlib import Path

from src.rebalance import compute_rebalance, export_outputs, load_positions, load_targets
from src.reporting import write_markdown_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a rebalance order list and summary report.")
    parser.add_argument("--positions", default="data/current_positions.csv", help="CSV with current portfolio positions.")
    parser.add_argument("--targets", default="data/target_allocations.csv", help="CSV with target weights.")
    parser.add_argument("--output-dir", default="reports/latest", help="Directory where reports and CSV outputs should be written.")
    parser.add_argument("--cash-buffer", default=0.02, type=float, help="Cash buffer weight to preserve after rebalancing.")
    parser.add_argument("--max-name-weight", default=0.18, type=float, help="Maximum single-name post-trade weight.")
    parser.add_argument("--max-region-weight", default=0.55, type=float, help="Maximum regional post-trade weight.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    positions = load_positions(args.positions)
    targets = load_targets(args.targets)
    result = compute_rebalance(
        positions,
        targets,
        cash_buffer_weight=float(args.cash_buffer),
        max_name_weight=float(args.max_name_weight),
        max_region_weight=float(args.max_region_weight),
    )

    output_dir = Path(args.output_dir)
    summary_path, orders_path, region_path, checks_path = export_outputs(result, output_dir)
    report_path = write_markdown_report(result, output_dir / "rebalance_report.md")

    print(f"Portfolio value: ${result.portfolio_value:,.0f}")
    print(f"Gross turnover: ${result.gross_turnover:,.0f}")
    print(f"Orders generated: {len(result.orders)}")
    print(f"Summary CSV: {summary_path}")
    print(f"Orders CSV: {orders_path}")
    print(f"Region CSV: {region_path}")
    print(f"Checks CSV: {checks_path}")
    print(f"Markdown report: {report_path}")


if __name__ == "__main__":
    main()
