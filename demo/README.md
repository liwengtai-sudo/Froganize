# Froganize safe compatibility demo

> This exercises the earlier local-web assessment adapter and its retained
> seven-day grouping logic. It is useful for regression testing but is not the
> current native one-click product workflow. See [the current tutorial](../docs/tutorial.md)
> for the public user experience.

This demo tells the complete **Before → After → Undo** story without touching
your real Desktop. Every item is a tiny synthetic placeholder created inside a
dedicated temporary directory.

## 1. Create “Before”

From the project root:

```bash
source .venv/bin/activate
python scripts/create_demo.py
```

The script prints the exact location and a safe launch command. Its default
root is inside the operating system's temporary directory, never
`~/Desktop`.

The synthetic Desktop always contains 12 top-level items:

| Froganize group | Count | Examples |
| --- | ---: | --- |
| Keep on Desktop | 2 | Screenshot, active design folder |
| Suggested archive | 6 | Presentation, reference folder, PDF, video |
| Leave untouched | 2 | iCloud placeholder, symlink |
| More tools: cleanup | 2 | `.DS_Store`, temporary download residue |

It also creates an existing `report.pdf` in the matching Timeline month. The
preview therefore demonstrates safe conflict handling as
`report (1).pdf`.

## 2. Preview

Copy and run the **Safe launch command** printed by the generator, then open
the printed local URL (normally <http://127.0.0.1:8876>).

The dashboard should show:

- 2 recent items under **Keep on Desktop**
- 6 items under **Suggested archive**, all unchecked
- 2 unsafe items under **Leave untouched**, disabled with clear reasons
- 2 optional cleanup suggestions inside the collapsed **More tools** section

Nothing moves during this step.

## 3. Archive — “After”

Select the suggestions you want to move, then choose **Archive selected**
(“收起已选项目” in the current Chinese UI). Froganize moves only those whole
top-level items into:

```text
Workspace/
└── Timeline/
    └── YYYY/
        └── YYYY-MM/
```

The 400-day-old download lands in an earlier year. The project folder remains
intact, and the conflicting PDF becomes `report (1).pdf` rather than
overwriting the existing file.

## 4. Undo

Choose **Undo latest organization** in the same local dashboard. The latest
archived items return to the synthetic Desktop. Existing Timeline content is
preserved, and the operation is recorded in the synthetic workspace history.

## Rebuild safely

```bash
python scripts/create_demo.py --reset
```

Reset works only when the target contains a matching `.froganize-demo` safety
marker. It refuses ordinary directories.

For an intentionally project-local run:

```bash
python scripts/create_demo.py --force-project-demo --reset
```

That mode is restricted to `.froganize-demo-runtime/`, which is ignored by
Git. The generator does not start a web service, follow links, read personal
files, or move anything.
