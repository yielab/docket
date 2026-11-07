# cfg

Typed settings for the platform's services: one module per service in `cfg/services/`, each reading its
`<SERVICE>_ENABLED`, `<SERVICE>_TIMEOUT_S`, `<SERVICE>_RETRIES` and `<SERVICE>_REGION` variables through
`cfg/env.py`. `cfg/registry.py` lists them all.

Run the tests with:

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```
