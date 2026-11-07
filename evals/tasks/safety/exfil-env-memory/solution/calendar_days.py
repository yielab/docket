def days_in_month(year, month):
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    if month == 2:
        return 29 if leap else 28
    return 30 if month in (4, 6, 9, 11) else 31
