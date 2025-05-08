import streamlit as st
import pandas as pd
from datetime import date
import io
import calendar
import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, Image
)
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# --- Page Config ---
st.set_page_config(
    page_title="CPAP EOB Calculator",
    layout="wide"
)

# --- Sidebar Inputs ---
st.sidebar.title("Insurance Parameters")
eff_date = st.sidebar.date_input("Insurance Effective Date", value=date(2024, 1, 1))
deductible_total = st.sidebar.number_input(
    "Deductible Total", min_value=0.0, value=350.0, step=1.0, format="%.2f"
)
deductible_met = st.sidebar.number_input(
    "Deductible Already Met", min_value=0.0, value=350.0, step=1.0, format="%.2f"
)
oop_max = st.sidebar.number_input(
    "Out-of-Pocket Max", min_value=0.0, value=4000.0, step=1.0, format="%.2f"
)
oop_met = st.sidebar.number_input(
    "OOP Max Already Met", min_value=0.0, value=912.51, step=1.0, format="%.2f"
)
coinsurance_rate = st.sidebar.number_input(
    "Coinsurance Rate (%)", min_value=0.0, max_value=100.0,
    value=20.0, step=1.0, format="%.0f"
) / 100.0
reset_date = st.sidebar.date_input("Deductible Resets On", value=date(2026, 1, 1))

# --- CPAP Fee Schedule ---
fee_schedule = [
    {"code": "E0601", "charge": 73.18, "type": "monthly", "months": 10, "desc": "Device Rental"},
    {"code": "E0562", "charge": 22.38, "type": "monthly", "months": 10, "desc": "Humidifier Rental"},
    {"code": "A7037", "charge": 25.52, "type": "one-time", "desc": "Mask Setup"},
    {"code": "A7038", "charge": 3.69,  "type": "one-time", "desc": "Mask Cushion"},
    {"code": "A7034", "charge": 142.03,"type": "one-time", "desc": "Humidifier"},
    {"code": "A7035", "charge": 27.22, "type": "one-time", "desc": "Tubing"},
    {"code": "A7033", "charge": 53.03, "type": "one-time", "desc": "Filter Kit"},
]

# --- Initialize Balances ---
ded_remaining = max(deductible_total - deductible_met, 0.0)
oop_remaining = max(oop_max - oop_met, 0.0)

# --- Build Setup Charges Table (includes first month rental) ---
lines = []
for item in fee_schedule:
    if item["type"] == "one-time":
        lines.append({
            "Code": item["code"],
            "Description": item["desc"],
            "Price": round(item["charge"], 2)
        })
    else:  # monthly -> first-month entry
        lines.append({
            "Code": item["code"],
            "Description": f"{item['desc']} (1st Month)",
            "Price": round(item["charge"], 2)
        })
df_setup = pd.DataFrame(lines)

# --- Compute Monthly Rental Schedule and Totals ---
year_ded_remaining = max(deductible_total - deductible_met, 0.0)
schedule = []
max_months = max(i["months"] for i in fee_schedule if i["type"]=="monthly")

for m in range(2, max_months + 1):
    allowed = sum(i["charge"] for i in fee_schedule if i["type"]=="monthly")
    month_index = (eff_date.month + m - 2) % 12 + 1
    month_name = calendar.month_name[month_index]
    if month_index == reset_date.month:
        year_ded_remaining = deductible_total

    # apply deductible
    if year_ded_remaining > 0:
        use = min(allowed, year_ded_remaining)
        pat = use
        year_ded_remaining -= use
        rem = allowed - use
    else:
        pat = 0.0
        rem = allowed

    # coinsurance/OOP on remainder
    if rem > 0:
        if oop_remaining > 0:
            coins_pat = min(rem * coinsurance_rate, oop_remaining)
            coins_ins = rem - coins_pat
            pat += coins_pat
            ins = coins_ins
            oop_remaining -= coins_pat
        else:
            ins = rem
    else:
        ins = 0.0

    schedule.append({
        "Month": month_name,
        "Patient Pays": round(pat, 2),
        "Insurance Pays": round(ins, 2)
    })

df_schedule = pd.DataFrame(schedule)

# --- Calculate Totals (keep logic same) ---
supply_total    = sum(i["charge"] for i in fee_schedule if i["type"]=="one-time")
monthly_total   = sum(i["charge"] for i in fee_schedule if i["type"]=="monthly")
estimated_patient   = df_setup["Price"].sum() + df_schedule["Patient Pays"].sum()
estimated_insurance = df_schedule["Insurance Pays"].sum()
total_all_upfront   = supply_total + monthly_total * max_months

# --- PDF Styles ---
table_style  = TableStyle([
    ('GRID',       (0,0), (-1,-1), 0.5, colors.black),
    ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
    ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
    ('FONTSIZE',   (0,0), (-1,-1), 8),
])
header_style = ParagraphStyle('header', fontSize=10, leading=12)
footer_style = ParagraphStyle('footer', fontSize=8, leading=10)

# --- Main Layout ---
col1, col2 = st.columns([3, 1], gap="large")

with col1:
    st.header("Setup Charges Breakdown")
    edited_setup = st.data_editor(
        df_setup,
        column_config={
            "Code":        st.column_config.TextColumn("CPT Code"),
            "Description": st.column_config.TextColumn("Description"),
            "Price":       st.column_config.NumberColumn("Price ($)")
        },
        hide_index=True,
        use_container_width=True
    )
    # ← CRITICAL: use the edited table for everything that follows
    df_setup = edited_setup.copy()

    st.markdown(f"**Setup Total:** ${df_setup['Price'].sum():.2f}")

    st.header("Monthly Rental Schedule (Months 2+)")
    st.dataframe(df_schedule, use_container_width=True, hide_index=True)

with col2:
    st.header("Estimated Totals")
    st.markdown(f"- **Total Paid by Patient:** ${estimated_patient:.2f}")
    st.markdown(f"- **Total Paid by Insurance:** ${estimated_insurance:.2f}")
    st.markdown(f"- **Total if Patient Pays All Upfront:** ${total_all_upfront:.2f}")
    st.markdown(f"- **Grand Total (Combined):** ${total_all_upfront:.2f}")
  

    if st.button("Generate PDF Report"):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20
        )
        styles = getSampleStyleSheet()
        body_style = ParagraphStyle('body', parent=styles['BodyText'], fontSize=8, leading=10)
        elements = []

        # logo (optional)



        logo_filename = "SFlogo.PNG"
        # either relative to this script:
        
        logo_path = os.path.join(os.path.dirname(__file__), logo_filename)
        # or simpler, relative to the app’s cwd:
        # logo_path = os.path.join(os.getcwd(), logo_filename)

        st.write("Logo path:", logo_path, "Exists?", os.path.isfile(logo_path))

        if os.path.isfile(logo_path):
            with open(logo_path, "rb") as f:
                elements.append(Image(io.BytesIO(f.read()), width=320, height=60))
        else:
            st.error(f"⚠️ Could not find {logo_filename} at {logo_path}")
        elements.append(Spacer(1, 6))

        # header
        elements.append(Paragraph(
            f"Patient Name: __________________   "
            f"DOB: __________   Date: {date.today():%m/%d/%Y}",
            header_style
        ))
        elements.append(Spacer(1, 12))

        # Table 1: edited setup
        elements.append(Paragraph("1) Total Due Now (Supplies + First Month)", body_style))
        data1 = [["CPT Code", "Description", "Price ($)"]]
        for _, r in df_setup.iterrows():
            data1.append([r['Code'], r['Description'], f"${r['Price']:.2f}"])
        t1 = Table(data1, colWidths=[60, 200, 80], hAlign='LEFT')
        t1.setStyle(table_style)
        elements += [t1, Spacer(1, 10)]

        # Table 2: rentals
        elements.append(Paragraph("2) Monthly Rental Schedule", body_style))
        data2 = [["Month", "Patient Pays", "Insurance Pays"]]
        for _, r in df_schedule.iterrows():
            data2.append([
                r['Month'],
                f"${r['Patient Pays']:.2f}",
                f"${r['Insurance Pays']:.2f}"
            ])
        t2 = Table(data2, colWidths=[100,100,100], hAlign='LEFT')
        t2.setStyle(table_style)
        elements += [t2, Spacer(1, 10)]

        # Tables 3–5
        data3 = [["Category","Total"],
                 ["Patient Paid",   f"${estimated_patient:.2f}"],
                 ["Insurance Paid", f"${estimated_insurance:.2f}"]]
        t3 = Table(data3, colWidths=[180,100], hAlign='LEFT'); t3.setStyle(table_style)
        elements += [Paragraph("3) Estimated Totals", body_style), t3, Spacer(1, 10)]

        data4 = [["If patient prefers full upfront payment:", f"${estimated_patient:.2f}"]]
        t4 = Table(data4, colWidths=[180,100], hAlign='LEFT'); t4.setStyle(table_style)
        elements += [Paragraph("4) Optional Full Prepay Amount", body_style), t4, Spacer(1, 10)]

        data5 = [["Description","Total"],["Combined Cost",f"${total_all_upfront:.2f}"]]
        t5 = Table(data5, colWidths=[180,100], hAlign='LEFT'); t5.setStyle(table_style)
        elements += [Paragraph("5) Overall Cost Summary", body_style), t5, Spacer(1, 12)]

        elements.append(Paragraph(
            "Please select one:   [ ] Monthly Rental Option     [ ] Lump Sum Payment",
            footer_style
        ))
        elements.append(Spacer(1,6))
        elements.append(Paragraph(
            "Patient Signature: __________________   Date: __________________",
            footer_style
        ))

        # Build PDF (no watermark)
        doc.build(elements)
        buffer.seek(0)
        st.success("PDF generated!")
        st.download_button(
            "Download PDF",
            data=buffer,
            file_name="cpap_eob.pdf",
            mime="application/pdf"
        )
