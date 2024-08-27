# Persistent record for link to survey

# External imports
import re
import logging
import time
# Local imports
from configuration import const as conf
from constants import Constants
import storage
from text import LogMessage
import user


# Constants
const = Constants()
const.LINK_KEY_LENGTH = 50


# If unit testing... exclude gCloud code
isUnitTest = ( __name__ == '__main__' )
if not isUnitTest:

    if conf.IS_CLOUD:
        from google.appengine.ext import ndb

        class LinkKey( ndb.Model ):
            destinationType = ndb.StringProperty()
            destinationId = ndb.StringProperty()
            loginRequired = ndb.BooleanProperty()
            timeCreated = ndb.IntegerProperty( default=0 )

    else:  # Database

        TABLE_NAME = conf.LINK_KEY_CLASS_NAME
        storage.databaseInitialize( f"""
            create table if not exists {TABLE_NAME} (
             id  varchar({const.LINK_KEY_LENGTH})  not null  primary key ,
             destinationType  varchar(32)  not null ,
             destinationId  int  not null ,
             loginRequired  bool  not null  default false ,
             timeCreated  int  not null
            )
        """ )


    def createRecord( *, id,  # long random alpha-numeric string
            destinationType,  # { REQUEST_CLASS_NAME, PROPOSAL_CLASS_NAME }
            destinationId,
            loginRequired=False,
            timeCreated ):
        if conf.IS_CLOUD:
            return LinkKeyGCloud( id=id, destinationType=destinationType, destinationId=destinationId, loginRequired=loginRequired, timeCreated=timeCreated )
        else:
            return storage.RecordDatabase.create( table=TABLE_NAME, fields={
                'id':id, 'destinationType':destinationType, 'destinationId':destinationId, 'loginRequired':loginRequired,
                'timeCreated':timeCreated
            } )

    # Creates link-key, stores link-key in persistent record
    def createAndStoreLinkKey( destClassName, destinationId, loginRequired ):
        linkKeyString = createLinkKey()
        logging.warning(LogMessage( 'linkKeyString=', linkKeyString ))

        linkKeyRecord = createRecord(
            id = linkKeyString,
            timeCreated = int( time.time() ) ,
            destinationType = destClassName,
            destinationId = destinationId,
            loginRequired = loginRequired
        )
        linkKeyRecord.put()
        return linkKeyRecord



def createLinkKey():
    return user.randomStringWithLength( const.LINK_KEY_LENGTH )

def isValidLinkKey( l ):
    return (l is not None) and (len(l) == const.LINK_KEY_LENGTH) and re.match( r'^[A-Za-z0-9]+$' , l )

def get_by_id( id ):
    if conf.IS_CLOUD:
        return LinkKey.get_by_id( id )
    else:  # Database
        return storage.RecordKeyDatabase( TABLE_NAME, id ).get()

def retrieveByTime( maxRecords=3, cursor=0 ):
    if conf.IS_CLOUD:
        linkRecords, cursor, hasMore = LinkKey.query().order( -LinkKey.timeCreated ).fetch_page( SURVEYS_PER_LOAD , start_cursor=cursor ) 
    else:
        linkRecords = storage.RecordDatabase.fetchall(
            f" select * from {TABLE_NAME}  order by timeCreated desc  limit {maxRecords}  offset {cursor} " ,
            table=TABLE_NAME
        )
        cursor = None
        hasMore = False
        if linkRecords and ( 0 < len(linkRecords) ):
            cursor = cursor + SURVEYS_PER_LOAD
            hasMore = True

    return linkRecords, cursor, hasMore
    



#################################################################################
# Unit test

if isUnitTest:

    import unittest

    class Tests( unittest.TestCase ):

        def test( self ):
            for i in range(1000):
                self.assertTrue(  isValidLinkKey( createLinkKey() )  )

    unittest.main()


