"""A CLI app: parameters from main's signature, a database by type, the result printed as JSON.

  archive                      since and db from the signature, dry_run from archive.yaml
  archive --since 3d --db pg-trix
  archive --schema             the parameters as JSON Schema
"""
from gppu import CliApp
from gppu.postgres import Postgres


class Archive(CliApp):
  def main(self, since: str = '7d', dry_run: bool = False, db: Postgres = 'pg-lake') -> dict:
    """Report what would be archived.

    Args:
      since: How far back to look.
      dry_run: Report without writing.
      db: The lake database.
    """
    self.Info('archiving', since, db)
    return {'since': since, 'dry_run': dry_run, 'db': db.uid}


if __name__ == '__main__': Archive.cli()
