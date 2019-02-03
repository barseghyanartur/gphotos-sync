#!/usr/bin/env python3
# coding: utf8
import os.path
import sqlite3 as lite
from sqlite3.dbapi2 import Connection, Row, Cursor
from datetime import datetime
from typing import Iterator

from gphotos import Utils
from gphotos.DbRow import DbRow
from gphotos.GooglePhotosRow import GooglePhotosRow
from gphotos.DatabaseMedia import DatabaseMedia

import logging

log = logging.getLogger(__name__)


class LocalData:
    DB_FILE_NAME: str = 'gphotos.sqlite'
    BLOCK_SIZE: int = 10000
    # this must match 'INSERT INTO Globals' in gphotos_create.sql
    VERSION: float = 5.0

    def __init__(self, root_folder: str, flush_index: bool = False):
        self.file_name: str = os.path.join(root_folder, LocalData.DB_FILE_NAME)
        if not os.path.exists(self.file_name) or flush_index:
            clean_db = True
        else:
            clean_db = False
        self.con: Connection = lite.connect(self.file_name,
                                            check_same_thread=False)
        self.con.row_factory: Row = lite.Row
        self.cur: Cursor = self.con.cursor()
        # second cursor for iterator functions so they can interleave with
        # others
        self.cur2: Cursor = self.con.cursor()
        if clean_db:
            self.clean_db()
        self.check_schema_version()

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.con:
            self.store()
            self.con.close()

    @DbRow.db_row
    class AlbumsRow(DbRow):
        """
        generates a class with attributes for each of the columns in the
        SyncFiles table
        """
        cols_def = {'AlbumId': str, 'AlbumName': str, 'Size': int,
                    'StartDate': datetime,
                    'EndDate': datetime, 'SyncDate': datetime}

    def check_schema_version(self):
        query = "SELECT  Version FROM  Globals WHERE Id IS 1"
        self.cur.execute(query)
        version = float(self.cur.fetchone()[0])
        if version > self.VERSION:
            raise ValueError('Database version is newer than gphotos-sync')
        elif version < self.VERSION:
            log.warning('Database schema out of date. Flushing index ...')
            self.con.commit()
            self.con.close()
            os.rename(self.file_name, self.file_name + '.previous')
            self.con = lite.connect(self.file_name)
            self.con.row_factory = lite.Row
            self.cur = self.con.cursor()
            self.clean_db()

    def clean_db(self):
        sql_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "sql", "gphotos_create.sql")
        with open(sql_file, 'r') as f:
            qry = f.read()
            self.cur.executescript(qry)

    def set_scan_date(self, last_date: datetime):
        d = Utils.date_to_string(last_date)
        self.cur.execute('UPDATE Globals SET LastIndex=? '
                         'WHERE Id IS 1', (d,))

    def get_scan_date(self) -> datetime:
        query = "SELECT LastIndex " \
                "FROM  Globals WHERE Id IS 1"
        self.cur.execute(query)
        res = self.cur.fetchone()

        d = res['LastIndex']
        if d:
            last_date = Utils.string_to_date(d)
        else:
            last_date = None

        return last_date

    def get_files_by_search(
            self, remote_id: str = '%',
            start_date: datetime = None,
            end_date: datetime = None,
            skip_downloaded: bool = False) -> Iterator[DatabaseMedia]:
        """
        Search for a selection of files in the SyncRow table.

        Parameters:
            remote_id: Google Photos unique ID
            start_date: start day for search
            end_date: end day for search
            skip_downloaded: Dont return entries already downloaded
        Return:
            An iterator over query results
        """
        params = (remote_id,)
        extra_clauses = ''
        if start_date:
            # look for create date too since an photo recently uploaded will
            # keep its original modified date (since that is in the exif)
            # this clause is specifically to assist in incremental download
            extra_clauses += 'AND (ModifyDate >= ? OR CreateDate >= ?)'
            params += (start_date, start_date)
        if end_date:
            extra_clauses += 'AND ModifyDate <= ?'
            params += (end_date,)
        if skip_downloaded:
            extra_clauses += 'AND Downloaded IS 0'

        query = "SELECT {0} FROM SyncFiles WHERE RemoteId LIKE ? {1};". \
            format(GooglePhotosRow.columns, extra_clauses)

        self.cur2.execute(query, params)
        while True:
            records = self.cur2.fetchmany(LocalData.BLOCK_SIZE)
            if not records:
                break
            for record in records:
                yield GooglePhotosRow(record).to_media()

    def get_file_by_path(self, folder: str, name: str):
        query = "SELECT {0} FROM SyncFiles WHERE Path = ?" \
                " AND FileName = ?;".format(GooglePhotosRow.columns)
        self.cur.execute(query, (folder, name))
        record = self.cur.fetchone()
        return GooglePhotosRow(record)

    def put_file(self, row, update=False):
        try:
            if update:
                query = "UPDATE SyncFiles Set {0} " \
                        "WHERE RemoteId = '{1}'".format(GooglePhotosRow.update,
                                                        row.RemoteId)
            else:
                query = "INSERT INTO SyncFiles ({0}) VALUES ({1})".format(
                    GooglePhotosRow.columns, GooglePhotosRow.params)
            self.cur.execute(query, row.dict)
            row_id = self.cur.lastrowid
        except lite.IntegrityError:
            log.error('SQL constraint issue with {}'.format(row.dict))
            raise
        return row_id

    def file_duplicate_no(self, name: str,
                          path: str, remote_id: str) -> (int, GooglePhotosRow):
        """
        determine if there is already an entry for file. If not determine
        if other entries share the same path/filename and determine a duplicate
        number for providing a unique local filename suffix

        Returns:
            duplicate no. (zero if there are no duplicates),
            Single row from the SyncRow table
        """
        query = "SELECT {0} FROM SyncFiles WHERE RemoteId = ?; ". \
            format(GooglePhotosRow.columns)
        self.cur.execute(query, (remote_id,))
        result = self.cur.fetchone()

        if result:
            # return the existing file entry's duplicate no.
            return result['DuplicateNo'], GooglePhotosRow(result)

        self.cur.execute(
            "SELECT MAX(DuplicateNo) FROM SyncFiles "
            "WHERE Path = ? AND OrigFileName = ?;", (path, name))
        results = self.cur.fetchone()
        if results[0] is not None:
            # assign the next available duplicate no.
            dup = results[0] + 1
            return dup, None
        else:
            # the file is new and has no duplicates
            return 0, None

    def get_album(self, album_id: str) -> AlbumsRow:
        query = "SELECT {0} FROM Albums WHERE AlbumId = ?;".format(
            self.AlbumsRow.columns)
        self.cur.execute(query, (album_id,))
        res = self.cur.fetchone()
        return self.AlbumsRow(res)

    def put_album(self, row: AlbumsRow) -> int:
        query = "INSERT OR REPLACE INTO Albums ({0}) VALUES ({1}) ;".format(
            row.columns, row.params)
        self.cur.execute(query, row.dict)
        return self.cur.lastrowid

    def get_album_files(self, album_id: str = '%'
                        ) -> (str, str, str, str):
        """ Join the Albums, SyncFiles and AlbumFiles tables to get a list
        of the files in an album or all albums.
        Parameters
            album_id: the Google Photos unique id for an album or None for all
            albums
        Returns:
            A tuple containing:
                Path, Filename, AlbumName, Album end date
        """
        self.cur.execute(
            "SELECT SyncFiles.Path, SyncFiles.Filename, Albums.AlbumName, "
            "Albums.EndDate FROM AlbumFiles "
            "INNER JOIN SyncFiles ON AlbumFiles.DriveRec=SyncFiles.RemoteId "
            "INNER JOIN Albums ON AlbumFiles.AlbumRec=Albums.AlbumId "
            "WHERE Albums.AlbumId LIKE ?;",
            (album_id,))
        results = self.cur.fetchall()
        # fetchall does not need to use cur2
        for result in results:
            yield tuple(result)

    def put_album_file(self, album_rec: str, file_rec: str):
        """ Record in the DB a relationship between an album and a media item
        """
        self.cur.execute(
            "INSERT OR REPLACE INTO AlbumFiles(AlbumRec, DriveRec) "
            "VALUES(?,"
            "?) ;",
            (album_rec, file_rec))

    def remove_all_album_files(self):
        # noinspection SqlWithoutWhere
        self.cur.execute("DELETE FROM AlbumFiles")

    def put_downloaded(self, sync_file_id: str, downloaded: bool = True):
        self.cur.execute(
            "UPDATE SyncFiles SET Downloaded=? "
            "WHERE RemoteId IS ?;", (downloaded, sync_file_id))

    def downloaded_count(self, downloaded: bool = True) -> int:
        self.cur.execute(
            "Select Count(Downloaded) from main.SyncFiles WHERE Downloaded=? ",
            (downloaded,))
        result = self.cur.fetchone()[0]
        return result

    def store(self):
        log.info("Saving Database ...")
        self.con.commit()
        log.info("Database Saved.")
