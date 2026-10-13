"""export_db: how the export walks the text stored in a copy of the history database - every table, every column, every distinct text value - and masks it in place."""


def text_columns(con):
    """(table, column) of every column of every table. The list of tables and of columns is read before the first one is given, so the caller may change the database while it walks."""
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        for _, column, *_rest in con.execute(f'PRAGMA table_info("{table}")').fetchall():
            yield table, column


def distinct_texts(con):
    """(table, column, value) of every distinct text value in the database."""
    for table, column in text_columns(con):
        for (value,) in con.execute(f"SELECT DISTINCT \"{column}\" FROM \"{table}\" WHERE typeof(\"{column}\") = 'text'"):
            yield table, column, value


def mask_text_columns(con, anon) -> None:
    """Every text value goes through the same replacement (the function is registered in the connection, so the database does it row by row), then the file is compacted."""
    con.create_function("anon", 1, lambda v: anon.text(v) if isinstance(v, str) else v)
    for table, column in text_columns(con):
        con.execute(f"UPDATE \"{table}\" SET \"{column}\" = anon(\"{column}\") WHERE typeof(\"{column}\") = 'text'")
    con.commit()
    con.execute("VACUUM")
