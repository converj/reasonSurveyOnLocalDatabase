# Wrapper on storage records for database or gcloud-datastore

from configuration import const as conf
# Import external modules
from collections import namedtuple
import datetime
import json
import logging
# Import app modules
import common
import text
from text import LogMessage



if conf.IS_CLOUD:
    from google.appengine.ext import ndb
    from google.cloud import storage as cloudStorage 

    logging.debug(LogMessage( 'Using g-cloud storage' ))

    imageBucket = None
    def getImageBucket( ):
        if not imageBucket:
            imageBucket = cloudStorage.Client().bucket( conf.STORAGE_BUCKET_IMAGES )
        return imageBucket

    def deleteBlob( imageId ):
        logging.debug(LogMessage( 'imageId=', imageId ))
        if ( imageId ):
            storageBucket = getImageBucket()
            storageBlob = storageBucket.blob( imageId )
            try:
                storageBlob.delete()
            except Exception as e:
                logging.error(LogMessage( 'Blob storage exception=', e ))

    def saveImage( imageId, imageFile, imageMimeType ):
        logging.debug(LogMessage( 'imageId=', imageId ))
        storageBucket = getImageBucket()
        storageBlob = storageBucket.blob( imageId )
        storageBlob.upload_from_file( imageFile, content_type=imageMimeType, rewind=True )

    
else:  # Database
    import mysql.connector

    logging.debug(LogMessage( 'Using local database storage' ))

    # Connect to local database
    databasePassword = None   # root or password
    with open( '/run/secrets/databasePassword' ) as inPassword:
        databasePassword = inPassword.read().strip()
    DATABASE_HOST = 'database'  # localhost or database
    DATABASE_NAME = 'procon'
    DATABASE_USER = 'proconuser'   # root or user
    databaseViewNames = None

    def databaseConnect( ):
        return mysql.connector.connect(
            host=DATABASE_HOST,  # Name of the mysql service as set in the docker compose file
            database=DATABASE_NAME,
            user=DATABASE_USER,
            password=databasePassword,
            auth_plugin='mysql_native_password',
            # Use pool_name if connecting is slow
        )

    def describeTable( tableName ):
        description, names, types = databaseExecAndFetchAll( f" describe {tableName} " )
        for d in description:
            logging.warning(LogMessage( '  ', d ))

    def logTables( ):
        tables, names, types = databaseExecAndFetchAll( "show full tables" )
        for t in tables:
            logging.warning(LogMessage( '  ', t ))
        for t in tables:
            describeTable( t[0] )

    def dropAllViews( ):
        names = getAllViewNames()
        if names:
            namesString = ' , '.join( list(names) )
            databaseExecute( f" drop view if exists {namesString} " )
        global databaseViewNames
        databaseViewNames = None

    def viewExists( viewName ):
        names = getAllViewNames()
        return ( viewName in names )

    def getAllViewNames( ):
        global databaseViewNames
        if databaseViewNames is None:
            viewRecords, names, types = databaseExecAndFetchAll( f" show full tables where table_type like 'VIEW' " )
            databaseViewNames = set( r[0] for r in viewRecords )
        return databaseViewNames

    def isZero( sql, parameterValues ):
        row, names, types = databaseExecAndFetchOne( sql, parameters=parameterValues )
        return ( row[0] == 0 )

    # Do not use null fields in database tables, because they are not comparable with "=null" (must use "is null")
    def databaseInitialize( sql ):
        logging.warning(LogMessage( 'sql=', sql ))
        with databaseConnect() as connection:
            with connection.cursor() as databaseCursorTemp:
                databaseCursorTemp.execute( sql )

    TABLE_NAME_IMAGE_BLOBS = 'image_blobs'
    databaseInitialize( f"""
        create table if not exists {TABLE_NAME_IMAGE_BLOBS} (
            id  varchar(32)  primary key  not null ,
            mime  varchar(32) ,
            data  blob  not null
        )
    """ )

    def deleteBlob( imageId ):
        if ( imageId ):
            databaseExecute( f" delete from {TABLE_NAME_IMAGE_BLOBS} where id=%s " , parameters=[imageId] )

    def saveImage( imageId, imageFile, imageMimeType ):
        logging.debug(LogMessage( 'imageId=', imageId ))
        imageFile.seek( 0 )
        imageData = imageFile.read()
        record = RecordDatabase.create( table=TABLE_NAME_IMAGE_BLOBS, fields={'id':imageId, 'mime':imageMimeType, 'data':imageData} )
        record.put()

    def timestampToDatetime( timeSeconds ):
        return datetime.datetime.fromtimestamp( timeSeconds ).strftime('%Y-%m-%d %H:%M:%S')

    def databaseExecAndFetchOne( sql, parameters=None ):  return databaseExecAndFetch( sql, parameters=parameters, fetchAll=False )

    def databaseExecAndFetchAll( sql, parameters=None ):  return databaseExecAndFetch( sql, parameters=parameters, fetchAll=True )

    def databaseExecAndFetch( sql, parameters=None, fetchAll=False ):
        with databaseConnect() as connection:
            return databaseExecAndFetchWithConnection( sql, parameters=parameters, fetchAll=fetchAll, connection=connection )

    # Because flask-server is multi-threaded, need separate connections for each possibly concurrent select statement
    #  Prevents "mysql.connector.errors.DatabaseError: 2014 (HY000): Commands out of sync"
    #  Always committing is not sufficient
    #  Separate cursor per select is not sufficient
    def databaseExecAndFetchWithConnection( sql, parameters=None, fetchAll=False, *, connection ):
        with connection.cursor() as databaseCursorTemp:
            logging.warning(LogMessage( 'sql=', sql ))
            if parameters:  logging.warning(LogMessage( 'parameters=', parameters ))
            else:  parameters = [ ]
            databaseCursorTemp.execute( sql, parameters )

            fieldNames = databaseCursorTemp.column_names
            fieldTypes = databaseCursorFieldTypes( databaseCursorArg=databaseCursorTemp )
            rows = databaseCursorTemp.fetchall()  if fetchAll  else databaseCursorTemp.fetchone()
            return rows, fieldNames, fieldTypes

    def databaseExecute( sql, parameters=None, commit=True ):
        with databaseConnect() as connection:
            databaseExecuteWithConnection( sql, parameters=parameters, commit=commit, connection=connection )

    def databaseExecuteWithConnection( sql, parameters=None, commit=True, *, connection ):
            with connection.cursor() as databaseCursorArg:
                logging.warning(LogMessage( 'sql=', sql ))
                if parameters:  logging.warning(LogMessage( 'parameters=', parameters ))
                else:  parameters = [ ]
                databaseCursorArg.execute( sql, parameters )
                if commit:  connection.commit()

    def databaseCursorFieldTypes( databaseCursorArg ):
        return [  mysql.connector.FieldType.get_info( f[1] )  for f in databaseCursorArg.description  ]

    # Initialize database
    #  TO DO:  If schema version changed... drop all views, add new table columns
    dropAllViews()
    logTables()




#########################################################################################################
# Uniform interface

def createKey( recordType, recordId ):
    if conf.IS_CLOUD:  return ndb.Key( recordType, recordId )
    else:               return RecordKeyDatabase( recordType, recordId )

def get_by_id( tableName, id ):
    return createKey( tableName, id ).get()

# Get several records by id-field
# Not for filtering by multiple fields, nor ranking, nor paging
def get_multi( keys ):
    logging.warning(LogMessage( f'keys={keys}' ))
    if conf.IS_CLOUD:
        return ndb.get_multi( keys )
    else:
        idParameters = ','.join( ['%s'] * len(keys) )
        idValues = [ k.id()  for k in keys ]
        tableName = keys[ 0 ].tableName  if keys  else None
        if not tableName:  return [ ]
        return RecordDatabase.fetchall( f" select * from `{tableName}` where `id` in ({idParameters}) " , parameters=idValues , table=tableName )


#########################################################################################################
# Record for mysql

class RecordKeyDatabase( object ):

    def __init__( self, tableName, id ):
        self.tableName = tableName
        self.idValue = id  # May be string or number

    def kind( self ):  return self.tableName

    def id( self ):  return self.idValue

    def get( self ):
        return RecordDatabase.retrieve( self.tableName, self.idValue )

    def __repr__( self ):  return f'{self.tableName}:{self.idValue}'


class RecordFieldDatabase( object ):

    DATETIME = 'DATETIME'
    JSON = 'JSON'
    NEWDECIMAL = 'NEWDECIMAL'

    def __init__( self, *, value, type, fromDatabase=False ):
        self.value = value
        self.changed = False
        self.type = type
        self.fromDatabase = fromDatabase

    def set( self, newValue ):
        self.changed = True
        self.value = newValue
        self.fromDatabase = False

    # Dangerous, should only be called after conversion toWebserverValue(), or it may prevent later conversion
    def touch( self ):
        self.changed = True
        self.fromDatabase = False

    # Does not change value to database form, because database form is only needed for storing, which is slow anyway
    def toDatabaseValue( self ):
        if self.fromDatabase:  return self.value

        if ( self.type == RecordFieldDatabase.DATETIME ):
            return datetime.datetime.fromtimestamp( self.value ).strftime('%Y-%b-%d %H:%M:%S')
        elif ( self.type == RecordFieldDatabase.JSON ):
            return json.dumps( self.value )

        return self.value

    # Changes value to webserver form, so that repeated reads do not cause repeated conversion
    def toWebserverValue( self ):
        if not self.fromDatabase:  return self.value

        if ( self.type == RecordFieldDatabase.DATETIME ):
            self.value = datetime.datetime.strptime( self.value, '%Y-%m-%d %H:%M:%S' )
        elif ( self.type == RecordFieldDatabase.JSON ):
            self.value = json.loads( self.value )  if self.value  else None
        elif ( self.type == RecordFieldDatabase.NEWDECIMAL ):
            self.value = float( self.value )  if self.value  else None

        self.fromDatabase = False
        return self.value

    def __repr__( self ):
        return f'{self.type}={self.value}' + ( '*' if self.changed else '' )



class RecordDatabase( object ):

    PRIVATE_VARS = [ 'key', '_fieldNameToOriginal', '_fieldNameToChange', '_fieldNameToType', '_fields' ]

    @staticmethod
    def retrieve( tableName, id ):
        return RecordDatabase.fetchone( table=tableName, sql=f" select * from `{tableName}` where `id`=%s ", parameters=[id] )

    @staticmethod
    def fetchone( sql, parameters=None, table=None ):
        row, names, types = databaseExecAndFetchOne( sql, parameters=parameters )
        return RecordDatabase.fromRow( table, row, names, types )

    @staticmethod
    def fetchall( sql, parameters=None, table=None ):
        rows, names, types = databaseExecAndFetchAll( sql, parameters=parameters )
        records = [ RecordDatabase.fromRow(table, row, names, types)  for row in rows  if row ]
        return records

    @staticmethod
    def fromRow( tableName, fieldNumberToValue, fieldNumberToName, fieldNumberToType ):
        if not fieldNumberToValue:  return None
        key = RecordKeyDatabase( tableName, None )
        fieldNameToValue = { fieldNumberToName[num] : value  for num,value in enumerate(fieldNumberToValue) }
        fieldNameToType =  { fieldNumberToName[n] : fieldNumberToType[n]  for n in range(len(fieldNumberToValue)) }
        record = RecordDatabase( key, fieldNameToValue, types=fieldNameToType, fromDatabase=True )
        record.key.idValue = record.id
        return record

    @staticmethod
    def create( *, table, id=None, fields, datetimes=None, jsons=None ):  # fields : map{name -> value}
        fieldNameToType = {}
        for name in datetimes or []:  fieldNameToType[ name ] = RecordFieldDatabase.DATETIME
        for name in jsons or []:  fieldNameToType[ name ] = RecordFieldDatabase.JSON
        if id:  fields['id'] = id
        return RecordDatabase( RecordKeyDatabase(table, None), fields, types=fieldNameToType, fromDatabase=False )

    def __init__( self, key, fieldNameToValue, types=None, *, fromDatabase ):
        self.key = key
        self._fields = {
            n : RecordFieldDatabase( value=v , type=types.get(n,None) if types else None , fromDatabase=fromDatabase )
            for n,v in fieldNameToValue.items()
        }

    def __setattr__( self, name, value ):
        if ( name in RecordDatabase.PRIVATE_VARS ):  self.__dict__[ name ] = value
        elif ( name in self._fields ):  self._fields[ name ].set( value )
        else:  self._fields[ name ] = RecordFieldDatabase( value=value, type=None, fromDatabase=False )

    def __getattr__( self, name ):
        if ( name in RecordDatabase.PRIVATE_VARS ):  return self.__dict__[ name ]
        if ( name in self._fields ):  return self._fields[ name ].toWebserverValue()
        else:  return None

    def touchField( self, name ):
        self._fields[ name ].touch()

    def put( self ):
        logging.warning(LogMessage( f'key={self.key}' ))
        logging.warning(LogMessage( f'_fields={self._fields}' ))

        # New record
        if not self.key.id():
            # Sequence the fields
            fieldNames = self._fields.keys()
            fieldValues = [ self._fields[name].toDatabaseValue()  for name in fieldNames ]

            # Insert new record to table
            fieldNamesStr = " , ".join( fieldNames )
            fieldParamsStr = " , ".join( ["%s"] * len(fieldValues) )
            with databaseConnect() as connectionTemp:
                databaseExecuteWithConnection(
                    f" insert into {self.key.kind()} ( {fieldNamesStr} ) values ( {fieldParamsStr} ) " ,
                    parameters=fieldValues ,
                    commit=False ,
                    connection=connectionTemp
                )

                # Set key id
                if self.id:
                    self.key.idValue = self.id
                else:
                    # Get auto-generated id
                    autoIdFields, names, types = databaseExecAndFetchWithConnection( f"select last_insert_id()", connection=connectionTemp )
                    logging.warning(LogMessage( 'autoIdFields=', autoIdFields ))
                    self.key.idValue = autoIdFields[ 0 ]

                connectionTemp.commit()   # Do not commit in databaseExecute() because it alters last_insert_id()
                return self.key

        # Retrieved record
        else:
            # Update existing record
            changedFieldNames = [ name  for name,field in self._fields.items()  if field.changed ]
            changedFieldValues = [ self._fields[name].toDatabaseValue()  for name in changedFieldNames ]
            fieldsStr = " , ".join(  [ f"{name}=%s" for name in changedFieldNames ]  )
            databaseExecute(
                f" update {self.key.kind()} set {fieldsStr} where id=%s " ,
                parameters= changedFieldValues + [ self.key.id() ]
            )
            return self.key


    def __repr__( self ):
        return f'key={self.key} _fields={self._fields}'



#########################################################################################################
# Query result continuation cursor

# TO DO:  Ditch the Cursor classes, just use browserToStorageCursor() and storageToBrowserCursor()

if conf.IS_CLOUD:

    class CursorGCloudDatastore( object ):

        def __init__( self, browserParam=None, storageParam=None ):
            if browserParam:  self.cursor = google.appengine.datastore.datastore_query.Cursor( browsersafe=browserParam )
            if storageParam:  self.cursor = storageParam

        def toBrowserParam( self ):
            return text.toUnicode( self.cursor.browsersafe() )  if self.cursor  else None

        def toStorageParam( self ):
            return self.cursor

else:  # Database
    class CursorDatabase( object ):

        def __init__( self, browserParam=None, storageParam=None ):
            if browserParam:  self.cursor = int( browserParam )  # Hold as storage-cursor, int for query offset
            if storageParam:  self.cursor = storageParam

        def toBrowserParam( self ):
            return str( self.cursor )  if self.cursor  else None

        def toStorageParam( self ):
            return self.cursor


def browserToStorageCursor( browserParam ):
    return __browserParamToCursor( browserParam ).toStorageParam()  if browserParam  else None

def storageToBrowserCursor( storageParam ):
    return __storageParamToCursor( storageParam ).toBrowserParam()  if storageParam  else None

def __browserParamToCursor( browserParam ):
    if not browserParam:  return None
    return CursorGCloudDatastore( browserParam=browserParam )  if conf.IS_CLOUD  else CursorDatabase( browserParam=browserParam )

def __storageParamToCursor( storageParam ):
    if not storageParam:  return None
    return CursorGCloudDatastore( storageParam=storageParam )  if conf.IS_CLOUD  else CursorDatabase( storageParam=storageParam )


