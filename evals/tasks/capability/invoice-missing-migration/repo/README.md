# Checkout service

Invoices are stored in SQLite. Schema changes are numbered files in `migrations/`, applied in name order by `store.migrate()`.

Run its project-visible tests with:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Keep the public function signatures stable.
