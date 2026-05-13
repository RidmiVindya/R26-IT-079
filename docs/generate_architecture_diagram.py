"""
Generates the high-level system architecture diagram for R26-IT-079
(Smart IoT-Driven Platform for Sustainable Dry Fish Processing).

Output: docs/system_architecture.png
"""

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT_PATH = Path(__file__).parent / "system_architecture.png"

CLOUD_COLOR = "#3B82F6"
INTEL_COLOR = "#1E3A8A"
MODULE_COLORS = ["#F59E0B", "#10B981", "#EF4444", "#8B5CF6"]
COMM_COLOR = "#F97316"
EDGE_COLOR = "#16A34A"
SIDE_COLOR = "#64748B"
TEXT_LIGHT = "#FFFFFF"
TEXT_DARK = "#0F172A"


def layer_box(ax, x, y, w, h, color, label, label_color=TEXT_LIGHT, fontsize=12):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.15",
        linewidth=1.2,
        edgecolor="#1F2937",
        facecolor=color,
    )
    ax.add_patch(box)
    ax.text(
        x + w / 2,
        y + h / 2,
        label,
        ha="center",
        va="center",
        fontsize=fontsize,
        color=label_color,
        fontweight="bold",
    )


def module_card(ax, x, y, w, h, color, title, subtitle):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.12",
        linewidth=1.2,
        edgecolor="#1F2937",
        facecolor=color,
    )
    ax.add_patch(box)
    ax.text(
        x + w / 2,
        y + h * 0.62,
        title,
        ha="center",
        va="center",
        fontsize=10.5,
        color=TEXT_LIGHT,
        fontweight="bold",
    )
    ax.text(
        x + w / 2,
        y + h * 0.28,
        subtitle,
        ha="center",
        va="center",
        fontsize=8.5,
        color=TEXT_LIGHT,
        style="italic",
    )


def small_label(ax, x, y, text, fontsize=9, color=TEXT_DARK):
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, color=color)


def arrow(ax, x1, y1, x2, y2, color="#374151"):
    ax.annotate(
        "",
        xy=(x2, y2),
        xytext=(x1, y1),
        arrowprops=dict(arrowstyle="-|>", color=color, lw=1.6, mutation_scale=14),
    )


def main():
    fig, ax = plt.subplots(figsize=(14, 10))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 11)
    ax.axis("off")

    ax.text(
        7,
        10.55,
        "R26-IT-079 — Smart IoT-Driven Dry Fish Processing Platform",
        ha="center",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=TEXT_DARK,
    )
    ax.text(
        7,
        10.15,
        "High-Level System Architecture (Hybrid Edge - Mobile - Cloud)",
        ha="center",
        va="center",
        fontsize=11,
        color="#475569",
        style="italic",
    )

    # Cloud Layer
    layer_box(ax, 3.5, 8.7, 7, 0.9, CLOUD_COLOR, "Cloud Layer")
    small_label(ax, 7, 8.45, "MongoDB Atlas  -  Analytics  -  Model Retraining", fontsize=9, color="#1E293B")

    # Intelligence Layer
    layer_box(ax, 3.5, 6.9, 7, 0.9, INTEL_COLOR, "Intelligence Layer")
    small_label(
        ax,
        7,
        6.65,
        "AI / ML Models   -   Random Forest, CNN, Gradient Boosting, Logistic Regression",
        fontsize=9,
        color="#1E293B",
    )

    # Module cards
    module_titles = [
        ("Predictive Drying\n& Spoilage", "FastAPI + Scikit-learn"),
        ("AI Quality Grading\n& Defect Detection", "TensorFlow + OpenCV"),
        ("Sustainability\n& Traceability", "Node.js + MongoDB"),
        ("Smart Drying\nEnvironment", "ESP32 + Real-time"),
    ]
    card_w, card_h = 2.6, 1.5
    start_x = 0.8
    gap = 0.45
    for i, (title, sub) in enumerate(module_titles):
        x = start_x + i * (card_w + gap)
        module_card(ax, x, 4.9, card_w, card_h, MODULE_COLORS[i], title, sub)

    # Communication Layer
    layer_box(ax, 3.5, 3.6, 7, 0.85, COMM_COLOR, "Communication Layer")
    small_label(
        ax,
        7,
        3.35,
        "REST APIs   -   Wi-Fi / HTTP   -   MQTT (planned)   -   Local SD Logging",
        fontsize=9,
        color="#1E293B",
    )

    # Edge Layer
    layer_box(ax, 3.5, 1.9, 7, 0.85, EDGE_COLOR, "Edge Layer")
    small_label(
        ax,
        7,
        1.65,
        "ESP32   -   DHT22 (Temp/Humidity)   -   HX711 + Load Cell   -   ESP32-CAM   -   MQ-136",
        fontsize=9,
        color="#1E293B",
    )

    # Mobile App (left side)
    layer_box(ax, 0.4, 6.9, 2.6, 0.9, SIDE_COLOR, "Flutter Mobile App", fontsize=11)
    small_label(ax, 1.7, 6.65, "Operator Dashboard", fontsize=9, color="#1E293B")

    # Alerts & Dashboard (right side)
    layer_box(ax, 11.0, 6.9, 2.6, 0.9, SIDE_COLOR, "Alerts & Dashboard", fontsize=11)
    small_label(ax, 12.3, 6.65, "Next.js Verification UI", fontsize=9, color="#1E293B")

    # Vertical arrows between layers
    arrow(ax, 7, 8.7, 7, 7.85)        # Cloud <- Intelligence
    arrow(ax, 7, 7.85, 7, 8.7)
    arrow(ax, 7, 6.9, 7, 6.45)        # Intelligence -> Modules
    arrow(ax, 7, 4.9, 7, 4.45)        # Modules -> Communication
    arrow(ax, 7, 4.45, 7, 4.9)
    arrow(ax, 7, 3.6, 7, 2.78)        # Communication -> Edge
    arrow(ax, 7, 2.78, 7, 3.6)

    # Side connectors
    arrow(ax, 3.0, 7.35, 3.5, 7.35)   # Mobile -> Intelligence
    arrow(ax, 3.5, 7.15, 3.0, 7.15)
    arrow(ax, 10.5, 7.35, 11.0, 7.35) # Intelligence -> Alerts
    arrow(ax, 11.0, 7.15, 10.5, 7.15)

    # Legend
    legend_handles = [
        mpatches.Patch(color=CLOUD_COLOR, label="Cloud Layer"),
        mpatches.Patch(color=INTEL_COLOR, label="Intelligence Layer"),
        mpatches.Patch(color=MODULE_COLORS[0], label="Predictive Drying & Spoilage"),
        mpatches.Patch(color=MODULE_COLORS[1], label="AI Quality Grading"),
        mpatches.Patch(color=MODULE_COLORS[2], label="Sustainability & Traceability"),
        mpatches.Patch(color=MODULE_COLORS[3], label="Smart Drying Environment"),
        mpatches.Patch(color=COMM_COLOR, label="Communication Layer"),
        mpatches.Patch(color=EDGE_COLOR, label="Edge Layer (IoT)"),
    ]
    ax.legend(
        handles=legend_handles,
        loc="lower center",
        ncol=4,
        bbox_to_anchor=(0.5, -0.02),
        fontsize=8.5,
        frameon=False,
    )

    plt.tight_layout()
    fig.savefig(OUT_PATH, dpi=180, bbox_inches="tight", facecolor="white")
    print(f"Saved: {OUT_PATH}")


if __name__ == "__main__":
    main()
