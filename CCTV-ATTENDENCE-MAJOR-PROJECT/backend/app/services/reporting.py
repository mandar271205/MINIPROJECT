from __future__ import annotations

from io import BytesIO

import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def _rows(records: list[dict]) -> list[dict]:
    return [
        {
            "Roll No": record["roll_number"],
            "Name": record["name"],
            "Status": record["status"],
        }
        for record in records
    ]


def generate_xlsx(records: list[dict]) -> BytesIO:
    output = BytesIO()
    df = pd.DataFrame(_rows(records))
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Attendance")
    output.seek(0)
    return output


def generate_pdf(records: list[dict], title: str) -> BytesIO:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=letter)
    width, height = letter
    y = height - 40

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, y, title)
    y -= 30

    pdf.setFont("Helvetica", 10)
    headers = ["Roll No", "Name", "Status"]
    pdf.drawString(40, y, " | ".join(headers))
    y -= 16

    for record in _rows(records):
        line = f"{record['Roll No']} | {record['Name']} | {record['Status']}"
        pdf.drawString(40, y, line)
        y -= 14
        if y < 40:
            pdf.showPage()
            y = height - 40
            pdf.setFont("Helvetica", 10)

    pdf.save()
    output.seek(0)
    return output
