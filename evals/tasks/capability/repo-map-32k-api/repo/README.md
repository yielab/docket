# api

A small read-only API: one module per resource in `api/resources/`, each listing a fixed sample
through `api.paging.paginate` (the first page is 1). `api/registry.py` lists them all.

Run the tests with:

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```
