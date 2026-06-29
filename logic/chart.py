from __future__ import annotations

import io
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from db import SpendEntry
from logic.formatting import aggregate_category_totals


def build_category_pie_image(
    rows: list[SpendEntry], today: date, exclude_one_off: bool = False
) -> bytes | None:
    totals = aggregate_category_totals(rows, today, exclude_one_off=exclude_one_off)
    if not totals:
        return None

    sorted_items = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    labels = [k for k, _ in sorted_items]
    amounts = [float(v) for _, v in sorted_items]
    grand_total = sum(amounts)

    colors = [
        "#cba6f7", "#89b4fa", "#94e2d5", "#a6e3a1",
        "#f9e2af", "#fab387", "#f38ba8", "#eba0ac",
        "#b4befe", "#74c7ec", "#a6e3a1", "#cdd6f4",
    ]

    fig, ax = plt.subplots(figsize=(7, 6))
    fig.patch.set_facecolor("#1e1e2e")
    ax.set_facecolor("#1e1e2e")

    wedges, _, autotexts = ax.pie(
        amounts,
        labels=None,
        autopct=lambda pct: f"{pct:.0f}%" if pct >= 3 else "",
        colors=colors[: len(labels)],
        startangle=140,
        pctdistance=0.75,
        wedgeprops={"linewidth": 2, "edgecolor": "#1e1e2e"},
    )
    for t in autotexts:
        t.set_color("white")
        t.set_fontsize(9)
        t.set_fontweight("bold")

    legend_labels = [
        f"{lbl}  ${amt:,.2f}  ({amt / grand_total * 100:.0f}%)"
        for lbl, amt in zip(labels, amounts)
    ]
    ax.legend(
        wedges,
        legend_labels,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.18),
        ncol=2,
        fontsize=8.5,
        frameon=False,
        labelcolor="white",
    )
    title = f"Spend by Category — {today.strftime('%B %Y')}"
    if exclude_one_off:
        title += " (excl. one-off)"
    ax.set_title(
        f"{title}\nTotal: ${grand_total:,.2f}",
        color="white",
        fontsize=12,
        pad=14,
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
