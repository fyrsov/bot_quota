import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ROLE_LABELS, Record, User
from bot.database.repositories.record_repo import RecordRepo
from bot.database.repositories.user_repo import UserRepo

_HEADER_FILL = PatternFill("solid", fgColor="4472C4")
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
_HEADER_ALIGN = Alignment(horizontal="center", vertical="center")
_BOLD = Font(bold=True)
_COL_WIDTHS = [5, 35, 15, 15, 20, 20]
_HEADERS = ["№", "ФИО", "Должность", "Telegram ID", "Номер договора", "Дата/время"]


def _write_sheet(ws, records: list[Record], user_map: dict[int, User], title: str) -> None:
    ws.title = title[:31]  # Excel ограничивает название листа 31 символом

    ws.append(_HEADERS)
    for col_idx in range(1, len(_HEADERS) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _HEADER_ALIGN

    for idx, record in enumerate(records, start=1):
        user = user_map.get(record.user_id)
        ws.append([
            idx,
            user.full_name if user else f"ID:{record.user_id}",
            ROLE_LABELS.get(user.role, user.role) if user else "—",
            record.user_id,
            record.site_number,
            record.created_at.strftime("%d.%m.%Y %H:%M") if record.created_at else "—",
        ])

    ws.append([])
    ws.append(["", "Итого выдано:", "", "", len(records), ""])
    total_row = ws.max_row
    ws.cell(row=total_row, column=2).font = _BOLD
    ws.cell(row=total_row, column=5).font = _BOLD

    for col_idx, width in enumerate(_COL_WIDTHS, start=1):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = width


async def build_excel(session: AsyncSession, months: list[str]) -> bytes:
    """
    Генерирует Excel-отчёт за список месяцев.
    Один месяц — один лист. Несколько — лист на каждый + сводный лист.
    months формат: ["2026-02", "2026-01", ...]
    """
    record_repo = RecordRepo(session)
    user_repo = UserRepo(session)

    users: list[User] = await user_repo.get_all()
    user_map: dict[int, User] = {u.telegram_id: u for u in users}

    wb = Workbook()
    wb.remove(wb.active)  # удаляем пустой лист по умолчанию

    all_records: list[Record] = []

    for month in sorted(months):
        records = await record_repo.get_by_month_all_users(month)
        all_records.extend(records)
        dt = datetime.strptime(month, "%Y-%m")
        sheet_title = dt.strftime("%B %Y")
        ws = wb.create_sheet(title=sheet_title)
        _write_sheet(ws, records, user_map, sheet_title)

    # Сводный лист если месяцев больше одного
    if len(months) > 1:
        ws_summary = wb.create_sheet(title="Сводная", index=0)
        _write_sheet(ws_summary, all_records, user_map, "Сводная")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()
