"""
app.py — SciDiploOntology Instrument Annotation
────────────────────────────────────────────────
Multi-annotator review tool for AI governance instruments.

Labels:
  ✅ Keep   — correct and relevant, include in knowledge graph
  ❌ Drop   — incorrect or irrelevant, exclude entirely
  🔍 Review — uncertain / keep with caveats

Annotations are stored per-annotator in the cloud database.
Multiple RAs can work concurrently; progress persists across sessions.

Run locally:
    streamlit run app.py

Requires DATABASE_URL in .streamlit/secrets.toml (or as env var).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from db_utils import (
    load_instruments,
    load_my_annotations,
    save_annotation,
    get_others_decisions,
    get_irr_stats,
)

# ── Paths ─────────────────────────────────────────────────────────────────
HERE = Path(__file__).parent
CRITERIA_CACHE_FILE = HERE / "criteria_cache.json"

# ── Label config ──────────────────────────────────────────────────────────
LABELS = ("Keep", "Drop", "Review")
LABEL_COLOR = {"Keep": "#1a7a3e", "Drop": "#c0392b", "Review": "#b7770d"}
LABEL_ICON  = {"Keep": "✅", "Drop": "❌", "Review": "🔍"}
LABEL_HELP  = {
    "Keep":   "Correct & relevant — include in the knowledge graph.",
    "Drop":   "Incorrect or irrelevant — exclude entirely.",
    "Review": "Partially useful but problematic — keep with caveats.",
}
SIDEBAR_ICON = {"Keep": "✅", "Drop": "❌", "Review": "🔍", None: "○"}

# ── Page config ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Instrument Annotation",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] .block-container { padding-top: 1rem; }
    .label-badge { font-size: 1.15rem; font-weight: 700; padding: 6px 14px;
                   border-radius: 6px; color: white; display: inline-block; }
    .others-row  { font-size: 0.85em; color: #555; margin: 4px 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Criteria cache ────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_criteria_cache() -> dict[str, dict]:
    if CRITERIA_CACHE_FILE.exists():
        try:
            return json.loads(CRITERIA_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


# ── Rendering helpers ─────────────────────────────────────────────────────
def badge_html(text: str, color: str = "#2471a3") -> str:
    return (
        f'<span style="background:{color};color:white;padding:2px 9px;'
        f'border-radius:4px;font-size:0.82em;font-weight:600;">{text}</span>'
    )

TYPE_COLORS: dict[str, str] = {
    "declaration": "#1a5276", "treaty": "#145a32", "framework": "#6e2f8c",
    "regulation":  "#7b241c", "standard": "#784212", "white_paper": "#2e4057",
    "resolution":  "#0e6655", "guideline": "#1a5276", "report": "#555",
    "agreement":   "#145a32", "convention": "#0e6655", "unknown": "#777",
}

_ASSESSMENT_COLOR = {
    "confirmed": "#1a7a3e", "plausible": "#b7770d",
    "unclear":   "#d35400", "unlikely":  "#c0392b",
}
_ASSESSMENT_ICON = {
    "confirmed": "🟢", "plausible": "🟡",
    "unclear":   "🟠", "unlikely":  "🔴",
}
_CRITERIA_FIELDS = [
    ("issuing_authority",        "Issuing authority"),
    ("authority_type",           "Authority type"),
    ("year",                     "Year"),
    ("adoption_mechanism",       "Adoption mechanism"),
    ("geographic_reach",         "Geographic reach"),
    ("governs_multiple_parties", "Governs multiple parties"),
    ("scope_summary",            "Scope"),
    ("is_specific_name",         "Specific name"),
]


def render_instrument_detail(inst: dict) -> None:
    st.markdown(f"## {inst['name']}")
    type_color = TYPE_COLORS.get(inst["instrument_type"].lower(), "#555")
    badges = badge_html(inst["instrument_type"], type_color)
    if inst["year"]:
        badges += f"&nbsp;&nbsp;{badge_html(str(inst['year']), '#7d6608')}"
    st.markdown(badges, unsafe_allow_html=True)
    st.markdown("")
    if inst["description"]:
        st.markdown(inst["description"])
    else:
        st.caption("*(no description stored)*")
    st.markdown("")


def render_criteria_card(criteria: dict) -> None:
    assessment = (criteria.get("assessment") or "unclear").lower()
    color  = _ASSESSMENT_COLOR.get(assessment, "#888")
    icon   = _ASSESSMENT_ICON.get(assessment, "⬜")
    reason = criteria.get("assessment_reason") or ""
    st.markdown(
        f'<div style="background:{color};color:white;padding:8px 14px;border-radius:6px;'
        f'font-size:1.05em;font-weight:700;margin-bottom:6px;">'
        f'{icon}&nbsp; {assessment.capitalize()}</div>',
        unsafe_allow_html=True,
    )
    if reason:
        st.caption(reason)
    st.markdown("")
    met, rows_html = 0, ""
    for field, label in _CRITERIA_FIELDS:
        val = criteria.get(field)
        if val is not None and val is not False and val != "":
            met += 1
            dot     = '<span style="color:#1a7a3e;font-size:1.1em;">✅</span>'
            val_str = str(val)
        else:
            dot     = '<span style="color:#aaa;font-size:1.1em;">⬜</span>'
            val_str = '<span style="color:#aaa;">—</span>'
        rows_html += (
            f'<tr><td style="padding:3px 8px 3px 0;white-space:nowrap;">{dot}</td>'
            f'<td style="padding:3px 8px;color:#555;font-size:0.88em;">{label}</td>'
            f'<td style="padding:3px 0;font-size:0.88em;">{val_str}</td></tr>'
        )
    score_color = "#1a7a3e" if met >= 6 else ("#b7770d" if met >= 3 else "#c0392b")
    st.markdown(
        f'<table style="border-collapse:collapse;width:100%;">{rows_html}</table>'
        f'<div style="margin-top:6px;font-weight:600;color:{score_color};">'
        f'{met}/{len(_CRITERIA_FIELDS)} criteria met</div>',
        unsafe_allow_html=True,
    )
    quote = criteria.get("best_quote")
    if quote:
        st.markdown(
            f'<blockquote style="border-left:3px solid {color};padding:4px 10px;'
            f'margin:10px 0 4px 0;color:#444;font-size:0.88em;font-style:italic;">'
            f'{quote}</blockquote>',
            unsafe_allow_html=True,
        )


# ── Export ────────────────────────────────────────────────────────────────
def build_export(instruments: list[dict], annotations: dict, annotator_id: str) -> tuple[str, str]:
    counts: dict[str, int] = {"Keep": 0, "Drop": 0, "Review": 0, "Unannotated": 0}
    results = []
    for inst in instruments:
        ann   = annotations.get(inst["name"], {})
        label = ann.get("label") or "Unannotated"
        if label not in counts:
            label = "Unannotated"
        counts[label] += 1
        results.append({
            "id": inst["id"], "name": inst["name"],
            "label": label, "notes": ann.get("notes", ""),
            "instrument_type": inst["instrument_type"], "year": inst["year"],
            "description": inst["description"], "source_urls": inst["source_urls"],
            "annotated_at": ann.get("annotated_at", ""),
        })
    export_json = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "annotator_id": annotator_id,
            "total": len(instruments),
            "annotated": len(instruments) - counts["Unannotated"],
            **{k.lower(): v for k, v in counts.items()},
        },
        "results": results,
    }

    def item_md(r: dict) -> str:
        lines = [f"### {r['name']}",
                 f"- **Type:** {r['instrument_type']}" + (f"  |  **Year:** {r['year']}" if r["year"] else "")]
        if r["notes"]:
            lines.append(f"- **Notes:** {r['notes']}")
        return "\n".join(lines)

    keep_r   = [r for r in results if r["label"] == "Keep"]
    drop_r   = [r for r in results if r["label"] == "Drop"]
    review_r = [r for r in results if r["label"] == "Review"]
    unann_r  = [r for r in results if r["label"] == "Unannotated"]

    md = [
        f"# Instrument Annotations — {annotator_id}",
        f"*{datetime.now().strftime('%Y-%m-%d %H:%M')}*", "",
        "## Summary", "| Label | Count |", "|-------|-------|",
        f"| ✅ Keep | {counts['Keep']} |", f"| ❌ Drop | {counts['Drop']} |",
        f"| 🔍 Review | {counts['Review']} |", f"| ○ Unannotated | {counts['Unannotated']} |",
        "", "---", "", f"## ✅ Keep ({len(keep_r)})", "",
    ]
    md += [item_md(r) + "\n" for r in keep_r] or ["*None.*\n"]
    md += ["---", "", f"## 🔍 Review ({len(review_r)})", ""]
    md += [item_md(r) + "\n" for r in review_r] or ["*None.*\n"]
    md += ["---", "", f"## ❌ Drop ({len(drop_r)})", ""]
    md += [item_md(r) + "\n" for r in drop_r] or ["*None.*\n"]
    md += ["---", "", f"## ○ Unannotated ({len(unann_r)})", ""]
    md += [f"- {r['name']}" for r in unann_r] or ["*None.*"]

    return json.dumps(export_json, indent=2, ensure_ascii=False), "\n".join(md)


# ── Session helpers ───────────────────────────────────────────────────────
def init_state(instruments: list[dict], annotator_id: str) -> None:
    if "annotations" not in st.session_state or st.session_state.get("_annotator") != annotator_id:
        st.session_state.annotations = load_my_annotations(annotator_id)
        st.session_state._annotator  = annotator_id
    if "criteria_cache" not in st.session_state:
        st.session_state.criteria_cache = load_criteria_cache()
    if "current_idx" not in st.session_state:
        ann = st.session_state.annotations
        st.session_state.current_idx = next(
            (i for i, inst in enumerate(instruments) if inst["name"] not in ann), 0
        )


def apply_label(name: str, label: str, notes: str, instruments: list[dict], idx: int, annotator_id: str) -> None:
    ann = st.session_state.annotations
    ann[name] = {"label": label, "notes": notes, "annotated_at": datetime.now(timezone.utc).isoformat()}
    save_annotation(name, annotator_id, label, notes)
    for j in range(idx + 1, len(instruments)):
        if "label" not in ann.get(instruments[j]["name"], {}):
            st.session_state.current_idx = j; return
    for j in range(0, idx):
        if "label" not in ann.get(instruments[j]["name"], {}):
            st.session_state.current_idx = j; return
    st.session_state.current_idx = idx


def go_to(idx: int, instruments: list[dict]) -> None:
    st.session_state.current_idx = max(0, min(idx, len(instruments) - 1))


# ── Main ──────────────────────────────────────────────────────────────────
def main() -> None:
    # ── Annotator ID ─────────────────────────────────────────────────────
    default_annotator = st.query_params.get("annotator", "")

    with st.sidebar:
        st.markdown("## 📋 Instrument Annotation")
        annotator_id = st.text_input(
            "Your name / initials",
            value=st.session_state.get("_annotator_input", default_annotator),
            placeholder="e.g. SP, JD, …",
            help="Your annotations are saved under this ID and persist across sessions.",
            key="_annotator_input",
        )

    if not annotator_id.strip():
        st.info(
            "👋 **Welcome!**  \n\n"
            "Enter your initials or name in the sidebar to start annotating.  \n"
            "Your progress persists across sessions."
        )
        st.stop()

    annotator_id = annotator_id.strip()

    # ── Load data ─────────────────────────────────────────────────────────
    instruments = load_instruments()
    if not instruments:
        st.error("No instruments found in the database.")
        st.stop()

    init_state(instruments, annotator_id)
    ann: dict[str, dict] = st.session_state.annotations
    idx: int = st.session_state.current_idx

    # ── Progress counts ───────────────────────────────────────────────────
    counts: dict[str, int] = {"Keep": 0, "Drop": 0, "Review": 0}
    for inst in instruments:
        lbl = ann.get(inst["name"], {}).get("label")
        if lbl in counts:
            counts[lbl] += 1
    annotated   = sum(counts.values())
    unannotated = len(instruments) - annotated

    # ── Sidebar ───────────────────────────────────────────────────────────
    with st.sidebar:
        st.caption(f"Annotating as: **{annotator_id}**")
        st.caption(f"Total instruments: **{len(instruments)}**")

        prog = annotated / len(instruments) if instruments else 0
        st.markdown(f"**My progress:** {annotated} / {len(instruments)} &nbsp;`{prog:.0%}`")
        st.progress(prog)

        c1, c2, c3 = st.columns(3)
        c1.metric("✅", counts["Keep"])
        c2.metric("❌", counts["Drop"])
        c3.metric("🔍", counts["Review"])
        st.caption(f"○ Unannotated: {unannotated}")

        # ── All-annotators IRR ────────────────────────────────────────────
        st.divider()
        with st.expander("👥 All Annotators", expanded=False):
            irr = get_irr_stats()
            if irr["annotators"]:
                st.caption(f"Active: {', '.join(irr['annotators'])}")
                st.markdown(
                    f"- **Annotated by ≥1 RA:** {irr['coverage_1plus']} / {len(instruments)}\n"
                    f"- **Annotated by ≥2 RAs:** {irr['coverage_2plus']}\n"
                    f"- **Full agreement (≥2 RAs):** {irr['agreement_count']}"
                )
                if irr["coverage_2plus"] > 0:
                    pct = irr["agreement_count"] / irr["coverage_2plus"] * 100
                    st.caption(f"Agreement rate: {pct:.0f}%")
                for ann_id, cnts in sorted(irr["per_annotator"].items()):
                    me = " ← you" if ann_id == annotator_id else ""
                    st.caption(
                        f"**{ann_id}**{me}: {cnts['total']} "
                        f"(✅{cnts['Keep']} ❌{cnts['Drop']} 🔍{cnts['Review']})"
                    )
                if irr["conflict_items"]:
                    st.markdown(f"**⚠️ Conflicts ({len(irr['conflict_items'])}):**")
                    for cname, clabels, canns in irr["conflict_items"][:10]:
                        parts = " / ".join(f"{a}→{LABEL_ICON.get(l,'?')}" for a, l in zip(canns, clabels))
                        short = cname[:48] + ("…" if len(cname) > 48 else "")
                        st.caption(f"• {short}  [{parts}]")
                    if len(irr["conflict_items"]) > 10:
                        st.caption(f"… and {len(irr['conflict_items']) - 10} more")
            else:
                st.caption("No annotations yet.")

        # ── Export ────────────────────────────────────────────────────────
        st.divider()
        json_str, md_str = build_export(instruments, ann, annotator_id)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button("⬇️ Download JSON", data=json_str,
            file_name=f"annotations_{annotator_id}_{ts}.json",
            mime="application/json", use_container_width=True)
        st.download_button("⬇️ Download Markdown", data=md_str,
            file_name=f"annotations_{annotator_id}_{ts}.md",
            mime="text/markdown", use_container_width=True)

        # ── Instrument list ───────────────────────────────────────────────
        st.divider()
        filter_txt       = st.text_input("Filter", placeholder="Search…", label_visibility="collapsed")
        only_unannotated = st.checkbox("Only unannotated", value=False)
        filter_lower     = filter_txt.lower()

        for i, inst in enumerate(instruments):
            name = inst["name"]
            lbl  = ann.get(name, {}).get("label")
            if filter_lower and filter_lower not in name.lower():
                continue
            if only_unannotated and lbl:
                continue
            icon  = SIDEBAR_ICON.get(lbl, "○")
            short = name[:44] + ("…" if len(name) > 44 else "")
            if st.button(f"{icon} {short}", key=f"nav_{i}",
                         use_container_width=True,
                         type="primary" if i == idx else "secondary"):
                go_to(i, instruments); st.rerun()

    # ── Main panel ────────────────────────────────────────────────────────
    inst        = instruments[idx]
    name        = inst["name"]
    current_ann = ann.get(name, {})
    cur_label   = current_ann.get("label")

    # Navigation bar
    n1, n2, n3, n4, n5 = st.columns([1, 1, 4, 1, 1])
    with n1:
        if st.button("⏮ First", use_container_width=True):
            go_to(0, instruments); st.rerun()
    with n2:
        if st.button("◀ Prev", use_container_width=True, disabled=(idx == 0)):
            go_to(idx - 1, instruments); st.rerun()
    with n3:
        pct = f"{(idx + 1) / len(instruments):.0%}"
        st.markdown(
            f"<div style='text-align:center;padding-top:6px;font-size:1.05em;'>"
            f"Instrument <b>{idx + 1}</b> of <b>{len(instruments)}</b> &nbsp;·&nbsp; {pct}</div>",
            unsafe_allow_html=True,
        )
    with n4:
        if st.button("Next ▶", use_container_width=True, disabled=(idx == len(instruments) - 1)):
            go_to(idx + 1, instruments); st.rerun()
    with n5:
        if st.button("Last ⏭", use_container_width=True):
            go_to(len(instruments) - 1, instruments); st.rerun()

    st.divider()

    # Two-column layout
    left, right = st.columns([3, 2], gap="large")

    with left:
        render_instrument_detail(inst)

        # Criteria card (from static cache)
        criteria = st.session_state.criteria_cache.get(name)
        if criteria:
            st.markdown("---")
            render_criteria_card(criteria)
        else:
            st.caption("*(No criteria analysis available for this instrument)*")

    with right:
        # Label badge
        if cur_label:
            color = LABEL_COLOR[cur_label]
            icon  = LABEL_ICON[cur_label]
            st.markdown(
                f'<div class="label-badge" style="background:{color};">'
                f'{icon}&nbsp; {cur_label}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="label-badge" style="background:#888;">○&nbsp; Unannotated</div>',
                unsafe_allow_html=True,
            )

        # Other annotators' decisions
        others = get_others_decisions(name, annotator_id)
        if others:
            parts = "  |  ".join(f"{a} → {LABEL_ICON.get(l, l)}" for a, l in others)
            st.markdown(f'<div class="others-row">Others: {parts}</div>', unsafe_allow_html=True)

        st.markdown("")

        # Notes
        notes_key = f"notes_{idx}"
        if notes_key not in st.session_state:
            st.session_state[notes_key] = current_ann.get("notes", "")

        st.markdown("**Notes**")
        notes_val = st.text_area("notes", key=notes_key, height=140,
            placeholder="Add observations, corrections, or context…",
            label_visibility="collapsed")

        st.markdown("")
        st.markdown("**Decision** — saves notes and advances to next unannotated")

        b1, b2, b3 = st.columns(3)
        with b1:
            keep = st.button("✅ Keep", use_container_width=True,
                type="primary" if cur_label == "Keep" else "secondary",
                help=LABEL_HELP["Keep"], key="btn_keep")
        with b2:
            drop = st.button("❌ Drop", use_container_width=True,
                type="primary" if cur_label == "Drop" else "secondary",
                help=LABEL_HELP["Drop"], key="btn_drop")
        with b3:
            review = st.button("🔍 Review", use_container_width=True,
                type="primary" if cur_label == "Review" else "secondary",
                help=LABEL_HELP["Review"], key="btn_review")

        if keep:   apply_label(name, "Keep",   notes_val, instruments, idx, annotator_id); st.rerun()
        if drop:   apply_label(name, "Drop",   notes_val, instruments, idx, annotator_id); st.rerun()
        if review: apply_label(name, "Review", notes_val, instruments, idx, annotator_id); st.rerun()

        st.divider()

        if st.button("💾 Save notes (no label change)", use_container_width=True, key="btn_save_notes"):
            entry = ann.get(name, {})
            entry["notes"] = notes_val
            ann[name] = entry
            save_annotation(name, annotator_id, cur_label, notes_val)
            st.success("Notes saved.")

        if st.button("⏭ Next unannotated", use_container_width=True, key="btn_skip"):
            for j in range(idx + 1, len(instruments)):
                if "label" not in ann.get(instruments[j]["name"], {}):
                    go_to(j, instruments); st.rerun(); break
            else:
                for j in range(0, idx):
                    if "label" not in ann.get(instruments[j]["name"], {}):
                        go_to(j, instruments); st.rerun(); break
                else:
                    st.info("All instruments annotated!")

        if cur_label:
            if st.button("↩ Clear label", use_container_width=True, key="btn_clear"):
                ann.pop(name, None)
                save_annotation(name, annotator_id, None, "")
                st.rerun()


if __name__ == "__main__":
    main()
