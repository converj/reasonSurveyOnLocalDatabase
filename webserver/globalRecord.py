# Import external modules
import datetime
import logging
import time
# Import local modules
from configuration import const as conf



GLOBAL_RECORD_ID = 'GLOBAL_RECORD_ID'
NEVER = -1

if conf.IS_CLOUD:
    from google.appengine.ext import ndb

    # Global record
    class GlobalRecord( ndb.Model ):

        adminPassword = ndb.StringProperty( indexed=False )

        # Cannot query all survey-types together, so keep separate update-times for each survey-type
        # TODO: Change to single json map{ surveyType -> latestUpdateTimeSec }
        latestMetricUpdateForProposal = ndb.IntegerProperty( default=NEVER )
        latestMetricUpdateForRequestProposals = ndb.IntegerProperty( default=NEVER )
        latestMetricUpdateForAutocomplete = ndb.IntegerProperty( default=NEVER )
        latestMetricUpdateForBudget = ndb.IntegerProperty( default=NEVER )
        latestMetricUpdateForMulti = ndb.IntegerProperty( default=NEVER )


        @staticmethod
        def new( ):  return GlobalRecord( id=GLOBAL_RECORD_ID )

        @staticmethod
        def retrieve( ):  return GlobalRecord.get_by_id(GLOBAL_RECORD_ID)


else:  # Database

    def newDatabase( ):  return storage.RecordDatabase.create( 'records', GLOBAL_RECORD_ID, {} )
    
    def retrieveDatabase( ):  return storage.RecordDatabase.retrieve( storage.RecordKeyDatabase('records', GLOBAL_RECORD_ID) )


################################################################################################
# Uniform interface

def new( ):
    if conf.IS_CLOUD:  return GlobalRecord.new()
    else:              return newDatabase()

def retrieve( ):
    if conf.IS_CLOUD:  return GlobalRecord.retrieve()
    else:              return retrieveDatabase()

def resetMetrics( record ):
    record.latestMetricUpdateForProposal = NEVER
    record.latestMetricUpdateForRequestProposals = NEVER
    record.latestMetricUpdateForAutocomplete = NEVER
    record.latestMetricUpdateForBudget = NEVER
    record.latestMetricUpdateForMulti = NEVER

def toDisplay( record ):
    return {
        'latestMetricUpdateForProposal': record.latestMetricUpdateForProposal ,
        'latestMetricUpdateForRequestProposals': record.latestMetricUpdateForRequestProposals ,
        'latestMetricUpdateForAutocomplete': record.latestMetricUpdateForAutocomplete ,
        'latestMetricUpdateForBudget': record.latestMetricUpdateForBudget ,
        'latestMetricUpdateForMulti': record.latestMetricUpdateForMulti ,
    }


