"""Artifacts panel v2 (Flet-only, MIT — our own code).

Companion to artifact_card.py: per-conversation registry + BottomSheet
panel + detail dialog with Copy/Download + real chart rendering via
ft.LineChart/ft.BarChart (built-ins). Pure parse/convert helpers tested.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field

import flet as ft

PANEL_MAX = 20


@dataclass
class ArtifactRecord:
    kind: str
    body: str
    reply_idx: int = 0


@dataclass
class ArtifactRegistry:
    """In-memory per-conversation artifact store (no DB change)."""

    items: dict[int, list[ArtifactRecord]] = field(default_factory=dict)

    def _key(self, conv_id: int | None) -> int:
        # Unsaved chats have conv_id None — keep them under sentinel 0 so
        # the panel works before the first DB save (old code dropped them).
        try:
            return int(conv_id) if conv_id is not None else 0
        except (TypeError, ValueError):
            return 0

    def add(self, conv_id: int | None, kind: str, body: str, reply_idx: int = 0) -> None:
        lst = self.items.setdefault(self._key(conv_id), [])
        lst.append(ArtifactRecord(kind, body[:8000], reply_idx))
        if len(lst) > PANEL_MAX:
            del lst[: len(lst) - PANEL_MAX]

    def list(self, conv_id: int | None) -> list[ArtifactRecord]:
        return list(self.items.get(self._key(conv_id), []))

    def clear(self, conv_id: int | None) -> None:
        self.items.pop(self._key(conv_id), None)

    def rebuild_from_texts(self, conv_id: int | None, texts: list[str]) -> int:
        """Re-extract artifacts from assistant texts (history reload).

        Returns the number of records stored. Used when opening an old
        chat whose registry was lost (in-memory only) or when the panel
        is opened and the registry is empty.
        """
        # Local import avoids a cycle (artifact_card never imports panel).
        try:
            from app.ui.widgets.artifact_card import extract_artifacts
        except Exception:
            return 0
        key = self._key(conv_id)
        self.items.pop(key, None)
        n = 0
        for idx, text in enumerate(texts or []):
            try:
                for kind, body in extract_artifacts(text or ""):
                    self.add(conv_id, kind, body, reply_idx=idx)
                    n += 1
                    if n >= PANEL_MAX:
                        return n
            except Exception:
                continue
        return n


def parse_chart_payload(body: str) -> dict | None:
    """Parse ```chart payload — None when invalid.

    Accepts:
    - {"labels": [...], "values": [...]}
    - {"data": [{"label": x, "value": n}, ...]} / {"data": [[label, value]]}
    - Markdown table rows (| Jan | 12 |) as a last resort.
    """
    text = (body or "").strip()
    if text:
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            labels = parsed.get("labels", [])
            values = parsed.get("values", [])
            if (not labels or not values) and isinstance(parsed.get("data"), list):
                labels, values = [], []
                for row in parsed["data"][:24]:
                    try:
                        if isinstance(row, dict):
                            labels.append(row.get("label", row.get("name", "")))
                            values.append(row.get("value", row.get("y", 0)))
                        elif isinstance(row, (list, tuple)) and len(row) >= 2:
                            labels.append(row[0])
                            values.append(row[1])
                    except Exception:
                        continue
            if isinstance(labels, list) and isinstance(values, list):
                if labels and len(labels) == len(values):
                    try:
                        nums = [float(v) for v in values]
                    except Exception:
                        nums = None
                    if nums is not None:
                        names = [str(l)[:24] for l in labels][:24]
                        return {"labels": names, "values": nums[:24]}
    # Fallback: markdown table (| label | value | rows). A header row
    # ("| Month | Sales |") fails numeric parse and is skipped; a single
    # data row still yields a one-bar chart (previously required >= 2 and
    # single-row tables silently produced no chart).
    try:
        pairs: list[tuple[str, float]] = []
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln or set(ln) <= set("|-: "):
                continue
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) >= 2:
                num = cells[1].replace(",", "").rstrip("%").lstrip("$€£₹").strip()
                try:
                    pairs.append((cells[0][:24] or "—", float(num)))
                except Exception:
                    continue
        if len(pairs) >= 1:
            return {"labels": [p[0] for p in pairs[:24]],
                    "values": [p[1] for p in pairs[:24]]}
    except Exception:
        pass
    return None


def artifact_to_csv(body: str) -> str:
    """Convert a table-ish body (| a | b | rows) to CSV text."""
    rows: list[list[str]] = []
    for ln in (body or "").splitlines():
        ln = ln.strip()
        if not ln or set(ln) <= set("|-: "):
            continue
        rows.append([c.strip() for c in ln.strip("|").split("|")])
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows[:50]:
        w.writerow(r)
    return buf.getvalue()


def artifact_to_text(kind: str, body: str) -> str:
    if kind == "json":
        try:
            return json.dumps(json.loads(body), indent=2, ensure_ascii=False)
        except Exception:
            pass
    if kind == "table":
        csv_text = artifact_to_csv(body)
        if csv_text.strip():
            return csv_text
    return (body or "")[:8000]


def chart_control(payload: dict) -> ft.Control:
    """Render a chart payload with whatever Flet offers.

    flet 0.86.5 ships no LineChart/BarChart widgets, so the primary
    renderer is pure-Flet proportional bars (Container/Row/Text — always
    available). Native charts are attempted first when present (future
    Flet versions), then bars, then plain text. Never raises.
    """
    try:
        labels: list[str] = list(payload.get("labels", []) or [])
        values: list[float] = list(payload.get("values", []) or [])
    except Exception:
        return ft.Text("(invalid chart data)", size=12, selectable=True)
    # Native charts when the Flet build provides them.
    try:
        if hasattr(ft, "LineChart") and hasattr(ft, "LineChartData"):
            points = [ft.LineChartDataPoint(float(i), float(v)) for i, v in enumerate(values)]
            series = [ft.LineChartData(data_points=points, stroke_width=2)]
            return ft.LineChart(data_series=series, height=180, expand=True)
    except Exception:
        pass
    try:
        if hasattr(ft, "BarChart") and hasattr(ft, "BarChartGroup"):
            groups = [
                ft.BarChartGroup(x=i, bar_rods=[ft.BarChartRod(to_y=float(v))])
                for i, v in enumerate(values)
            ]
            return ft.BarChart(bar_groups=groups, height=180, expand=True)
    except Exception:
        pass
    # Pure-Flet horizontal bars (works on every Flet/Android build).
    try:
        pairs = [(str(l)[:24], float(v)) for l, v in zip(labels, values)][:24]
    except Exception:
        return ft.Text("(invalid chart data)", size=12, selectable=True)
    if not pairs:
        return ft.Text("(empty chart)", size=12, selectable=True)
    try:
        vmax = max(abs(v) for _, v in pairs) or 1.0
        rows: list[ft.Control] = []
        for lab, val in pairs:
            frac = min(1.0, abs(val) / vmax)
            rows.append(
                ft.Row(
                    [
                        ft.Text(lab, size=11, width=90,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Container(
                            content=ft.Text(
                                f"{val:g}", size=10,
                                color=ft.Colors.ON_PRIMARY,
                                max_lines=1, overflow=ft.TextOverflow.CLIP,
                            ),
                            width=max(36, int(200 * frac)),
                            bgcolor=ft.Colors.PRIMARY,
                            border_radius=6,
                            padding=4,
                            tooltip=f"{lab}: {val:g}",
                        ),
                    ],
                    spacing=8,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        return ft.Column(rows, spacing=6, tight=True, scroll=ft.ScrollMode.AUTO)
    except Exception:
        try:
            return ft.Text("\n".join(f"{l}: {v}" for l, v in zip(labels, values))[:1000],
                           size=12, selectable=True)
        except Exception:
            return ft.Text("(chart unavailable)", size=12)


def download_name(kind: str, idx: int) -> tuple[str, str]:
    ext = {"table": "csv", "json": "json", "chart": "json"}.get(kind, "md")
    return (f"artifact-{idx}.{ext}", ext)


def build_artifact_panel(records: list[ArtifactRecord], on_open) -> ft.Column:
    items: list[ft.Control] = []
    if not records:
        return ft.Column([ft.Text("No artifacts yet — ask for a table or chart.", size=12)],
                         spacing=4, tight=True)
    for i, rec in enumerate(records):
        preview = rec.body.strip().splitlines()
        head = (preview[0][:60] + "…") if preview and len(preview[0]) > 60 else (preview[0] if preview else rec.kind)
        items.append(
            ft.ListTile(
                leading=ft.Icon(ft.Icons.DASHBOARD_OUTLINED, size=20),
                title=ft.Text(f"{rec.kind.title()} #{i + 1}", size=13),
                subtitle=ft.Text(head, size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18),
                data=i,
                on_click=on_open,
            )
        )
    return ft.Column(items, spacing=0, tight=True, scroll=ft.ScrollMode.AUTO)
