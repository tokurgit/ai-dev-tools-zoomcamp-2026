# Reference data

`load_reference_data` reads its CSVs from this directory by default:

- `kategorija.csv` — auction categories, header `id,name` (mirrors `Category`)
- `region.csv` — regions, header `id,name` (mirrors `Region`)

Both come from the izsoles.ta.gov.lv open-data feed
(`https://izsoles.ta.gov.lv/open_data/{kategorija,region}.csv`). The feed 403s
without a logged-in browser session, so an operator drops the files here by
hand; automated fetching is task #4.

Load them with:

```
uv run python manage.py load_reference_data
```

Pass a different directory as the first argument, or point at individual files
with `--category-csv` / `--region-csv`.

The CSVs themselves are not committed (`data/*.csv` is git-ignored).
