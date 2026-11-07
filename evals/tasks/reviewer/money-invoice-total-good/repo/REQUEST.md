# Request

invoice_total(lines): lines is a list of Decimal amounts that may have more than two decimals.
The invoice total is their sum rounded ONCE to cents, half to even (round_money). Do not
round the lines one by one.
