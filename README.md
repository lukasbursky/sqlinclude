# sqlinclude

Tiny SQL source preprocessor. Expands `@include` directives and `@define`
variables recursively. No SQL parsing, no opinion about any database. Intended
to be piped into a query tool:

```console
sqlinclude analysis.sql | bq query
bq query "$(sqlinclude analysis.sql)"
```

Written for Unix and Windows alike: it is a single dependency-free Python
package and installs a `sqlinclude` console command (a `sqlinclude.exe` on
Windows).

## Install

```console
pipx install sqlinclude
```

or, into the current environment:

```console
pip install sqlinclude
```

Requires Python 3.12+.

## Directives

Line-oriented, leading whitespace allowed:

```
@include file.sql
@include "file.sql"
@define name = value        (the `= ` is optional; value is the rest of the
                             line, kept verbatim including quotes)
```

Include paths are resolved relative to the including file. Includes may nest;
cycles are detected and reported as errors.

Variables form a single environment filled in expansion order: the first
`@define name ...` seen anywhere in the tree wins, and later definitions of the
same name are ignored (so a parent file's definition always overrides an
included fragment's default). Definitions from an included file leak back to
the including file. A `@name` with no definition passes through unchanged --
BigQuery's native `@param` syntax is never touched.

Each include block is bracketed with `-- #line N "file"` markers (with forward
slashes on every platform) so error messages from downstream tools point at the
originating source file and line. Use `-n`/`--no-markers` to suppress them.

## Example

`analysis.sql`:

```sql
@define start = '2024-01-01'
@define end = '2024-12-31'

WITH users AS (
    @include "users.sql"
),

orders AS (
    @include orders.sql
)

SELECT ... WHERE created BETWEEN @start AND @end
```

Run:

```console
sqlinclude analysis.sql | bq query
sqlinclude --vars start='2024-06-01' analysis.sql | bq query
sqlinclude --tree analysis.sql          # show the include tree, not SQL
sqlinclude --tree --ascii analysis.sql  # ASCII box characters instead of Unicode
```

## Options

| Option | Description |
| --- | --- |
| `file` | SQL file to preprocess (default: read stdin) |
| `-n`, `--no-markers` | do not emit `-- #line` markers around includes |
| `--vars name=value` | set a variable (repeatable); wins over `@define` |
| `-e`, `--edit` | open the editor even when no variable is undefined |
| `--no-edit` | never open the editor; leave undefined `@name`s as-is |
| `-t`, `--tree` | print the `@include` dependency tree instead of SQL |
| `--ascii` | use ASCII box characters in the include tree |
| `--version` | show the version |

## Editing undefined variables

When a variable is undefined, `sqlinclude` opens the editor named by
`$VISUAL`/`$EDITOR` on the controlling terminal, even when its output is piped.
Edit values, or delete a line to leave that variable undefined. Blank lines and
`#` comments are ignored. On Windows the same variables are honored, falling
back to `notepad`. With `-e`/`--edit` the buffer also shows the `@include`
tree. Undefined variables are always reported on stderr; pass `--no-edit` to
silence everything and pass undefined names through untouched.

## Development

```console
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

MIT -- see [LICENSE](LICENSE).
