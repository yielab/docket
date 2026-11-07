# Request

needs_refresh(issued_at, now, margin=10): True when the token has at most margin seconds left
(exactly margin included), and also once it is expired. Remaining life is 60 s minus the age.
