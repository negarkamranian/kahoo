from backend.services.database_archives import backup_database, restore_database


def backup(args):
    return backup_database(args.directory)


def restore(args):
    return restore_database(args.archive, args.database)
