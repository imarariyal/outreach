"""Outreach Dashboard (read-only).

Reads the Outreach tab of the outreach workbook and shows:
  Overview  - where every campaign stands
  Coverage  - which regions / companies each campaign has reached
  Actions   - what to do next, warmest first
  All rows  - the full filtered list

Data source, in this order:
  1. csv_url in .streamlit/secrets.toml (or the CSV_URL environment variable):
     the "Publish to web" CSV link of the Outreach tab in Google Sheets.
  2. A local Excel file next to this script (Outreach_Workbook_MOCK.xlsx or
     Outreach_Workbook.xlsx), for trying the app without publishing anything.

To switch from mock to real data, change csv_url. Nothing else changes.
"""
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Outreach Dashboard", page_icon="📬", layout="wide")

HERE = Path(__file__).parent
LOCAL_FILES = ["Outreach_Workbook_MOCK.xlsx", "Outreach_Workbook.xlsx"]
STATUSES = ["To find contact", "Ready to send", "Sent", "Opened / Accepted", "Replied", "Meeting booked",
            "Proposal sent", "Won", "Lost / Not interested", "Bounced / Wrong person"]
NOT_CONTACTED = ["To find contact", "Ready to send"]
ENGAGED = ["Opened / Accepted", "Replied", "Meeting booked", "Proposal sent", "Won"]
HIDE_ACTIONS = ["", "Wait for reply", "Close", "Hand over to delivery"]
REQUIRED = ["Campaign", "Company ID", "Company", "Region", "Contact name", "Role", "Status", "Next action",
            "Action order", "Last touch date", "Sent to (email / LinkedIn)"]


# ------------------------------------------------------------------ data
def csv_url() -> str:
    try:
        url = st.secrets.get("csv_url", "")
    except Exception:  # no secrets file
        url = ""
    return url or os.environ.get("CSV_URL", "")


@st.cache_data(ttl=300, show_spinner="Loading outreach data...")
def load(url: str) -> tuple[pd.DataFrame, str]:
    if url:
        df, source = pd.read_csv(url, dtype=str, keep_default_na=False), "Published Google Sheet"
    else:
        path = next((HERE / f for f in LOCAL_FILES if (HERE / f).exists()), None)
        if path is None:
            raise FileNotFoundError("No csv_url set and no local workbook found next to app.py.")
        df = pd.read_excel(path, sheet_name="Outreach", dtype=str).fillna("")
        source = f"Local file: {path.name}"
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"These columns are missing from the Outreach tab: {', '.join(missing)}")
    df = df[(df["Campaign"].str.strip() != "") | (df["Company ID"].str.strip() != "")].copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip().replace({"nan": "", "None": ""})
    df["Company"] = df["Company"].replace("", "(unknown company)")
    df["Last touch date"] = pd.to_datetime(df["Last touch date"], errors="coerce").dt.date
    df["Days since last touch"] = pd.to_numeric(df.get("Days since last touch", ""), errors="coerce")
    df["Action order"] = pd.to_numeric(df["Action order"], errors="coerce").fillna(9)
    df["Contacted"] = (~df["Status"].isin(NOT_CONTACTED)).astype(int)
    df["Engaged"] = df["Status"].isin(ENGAGED).astype(int)
    df["Bounced"] = (df["Status"] == "Bounced / Wrong person").astype(int)
    df["No contact yet"] = (df["Status"] == "To find contact").astype(int)
    return df, source


try:
    df, source = load(csv_url())
except Exception as e:
    st.error(f"Could not load the data. {e}")
    st.stop()

# ------------------------------------------------------------------ sidebar
st.sidebar.title("Filters")


def pick(label, col, options=None):
    opts = options or sorted(v for v in df[col].unique() if v)
    return st.sidebar.multiselect(label, opts, placeholder="All")


f_campaign = pick("Campaign", "Campaign")
f_region = pick("Region", "Region")
f_status = pick("Status", "Status", [s for s in STATUSES if s in set(df["Status"])])
search = st.sidebar.text_input("Search company or person")

view = df
for chosen, col in [(f_campaign, "Campaign"), (f_region, "Region"), (f_status, "Status")]:
    if chosen:
        view = view[view[col].isin(chosen)]
if search:
    s = search.lower()
    view = view[view["Company"].str.lower().str.contains(s, regex=False)
                | view["Contact name"].str.lower().str.contains(s, regex=False)]

st.sidebar.divider()
if st.sidebar.button("🔄 Refresh data", width="stretch"):
    load.clear()
    st.rerun()
st.sidebar.caption(f"Source: {source}")
st.sidebar.caption("Updates in the sheet appear within about 5 minutes.")

# ------------------------------------------------------------------ header
st.title("📬 Outreach Dashboard")
is_mock = "Found on tabs" in df.columns and (df["Found on tabs"] == "Mock data").mean() > 0.5
if is_mock:
    st.warning("Demo mode: this dashboard is showing made-up data.", icon="🧪")

k = st.columns(5)
k[0].metric("Companies targeted", view["Company ID"].nunique())
k[1].metric("People contacted", int(view["Contacted"].sum()))
k[2].metric("Engaged", int(view["Engaged"].sum()), help="Opened, accepted, replied, meeting, proposal or won")
k[3].metric("Bounced / wrong person", int(view["Bounced"].sum()))
k[4].metric("No contact yet", help="Companies where no person has been found yet", value= view.loc[view["No contact yet"] == 1, "Company ID"].nunique())

tab_over, tab_cov, tab_act, tab_all = st.tabs(["📊 Overview", "🌍 Coverage", "✅ What to do next", "📋 All rows"])

# ------------------------------------------------------------------ overview
with tab_over:
    summary = (view.groupby("Campaign")
               .agg(Companies=("Company ID", "nunique"), Rows=("Campaign", "size"), Contacted=("Contacted", "sum"),
                    Engaged=("Engaged", "sum"), Bounced=("Bounced", "sum"), No_contact=("No contact yet", "sum"))
               .rename(columns={"No_contact": "No contact yet", "Rows": "People / targets"})
               .sort_values("Contacted", ascending=False))
    summary["Engagement rate"] = (summary["Engaged"] / summary["Contacted"].where(summary["Contacted"] > 0)).fillna(0)
    st.subheader("Campaigns at a glance")
    st.dataframe(summary, width="stretch",
                 column_config={"Engagement rate": st.column_config.ProgressColumn(
                     "Engagement rate", format="percent", min_value=0, max_value=1)})

    st.subheader("Where everyone is, by campaign")
    by = view.groupby(["Campaign", "Status"]).size().reset_index(name="People")
    st.altair_chart(
        alt.Chart(by).mark_bar().encode(
            y=alt.Y("Campaign:N", title=None, sort="-x"),
            x=alt.X("People:Q", title="People / targets"),
            color=alt.Color("Status:N", sort=STATUSES, scale=alt.Scale(domain=STATUSES, scheme="tableau10")),
            order=alt.Order("status_order:Q"),
            tooltip=["Campaign", "Status", "People"],
        ).transform_calculate(status_order=f"indexof({STATUSES}, datum.Status)"),
        width="stretch")

# ------------------------------------------------------------------ coverage
with tab_cov:
    st.subheader("Companies reached, by campaign and region")
    st.caption("Each cell: companies with at least one person contacted / companies targeted.")
    targeted = view.pivot_table(index="Campaign", columns="Region", values="Company ID", aggfunc="nunique",
                                fill_value=0)
    reached = (view[view["Contacted"] == 1]
               .pivot_table(index="Campaign", columns="Region", values="Company ID", aggfunc="nunique", fill_value=0)
               .reindex(index=targeted.index, columns=targeted.columns, fill_value=0))
    cells = reached.astype(str) + " / " + targeted.astype(str)
    cells = cells.where(targeted > 0, "")
    st.dataframe(cells, width="stretch")

    st.subheader("Company by company")
    comp = (view.groupby(["Campaign", "Region", "Company"])
            .agg(People=("Company", "size"), Contacted=("Contacted", "sum"), Engaged=("Engaged", "sum"),
                 Bounced=("Bounced", "sum"))
            .reset_index())
    comp["State"] = comp.apply(
        lambda r: "Engaged" if r.Engaged else ("Contacted" if r.Contacted else "Not reached yet"), axis=1)
    order = {"Not reached yet": 0, "Contacted": 1, "Engaged": 2}
    comp = comp.sort_values(["State", "Campaign", "Region"], key=lambda c: c.map(order) if c.name == "State" else c)
    st.dataframe(comp, hide_index=True, width="stretch", height=420)

# ------------------------------------------------------------------ actions
with tab_act:
    todo = view[~view["Next action"].isin(HIDE_ACTIONS)].sort_values(["Action order", "Campaign", "Company"])
    st.write(f"**{len(todo)} things to do**, warmest first.")
    cols = ["Company", "Contact name", "Role", "Campaign", "Region", "Status", "Last touch date",
            "Sent to (email / LinkedIn)"]
    for action, g in todo.groupby("Next action", sort=False):
        with st.expander(f"{action} ({len(g)})", expanded=bool(g["Action order"].iloc[0] <= 2)):
            st.dataframe(g[cols], hide_index=True, width="stretch")
    waiting = view[view["Next action"] == "Wait for reply"]
    if len(waiting):
        st.caption(f"{len(waiting)} people are waiting on a reply and are hidden here.")

# ------------------------------------------------------------------ all rows
with tab_all:
    show = view.drop(columns=["Contacted", "Engaged", "Bounced", "No contact yet"])
    st.dataframe(show, hide_index=True, width="stretch", height=600)
    st.download_button("Download this view (CSV)", show.to_csv(index=False), "outreach_view.csv", "text/csv")
