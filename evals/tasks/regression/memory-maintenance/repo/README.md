# Checkout service

This tiny service calculates invoice totals and produces receipt metadata.

Run its project-visible tests with:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Keep the public function signatures stable. Durable product decisions are maintained by the pod
Lead rather than duplicated in this repository.
