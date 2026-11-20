"""PostgreSQL connection adapter for VeriCite's parameterized repository queries."""
import psycopg
from psycopg.rows import dict_row


class PostgresConnection(psycopg.Connection):
    def execute(self, query, params=None):
        return super().execute(query.replace("?", "%s"), params)

    def executemany(self, query, params):
        with self.cursor() as cursor:
            cursor.executemany(query.replace("?", "%s"), params)


def connect(url):
    return PostgresConnection.connect(url, row_factory=dict_row)
