# Data-record class for a single participant's answers to multi-question-survey

# External modules
from collections import Counter, namedtuple
import hashlib
import logging
import re
# Application modules
from multi.configMulti import conf
import multi.survey
import multi.voteAggregates
import storage
import text
from text import LogMessage
import user


# Answer data-structure for easier reading by caller
KEY_CONTENT = 'content'
KEY_REASON = 'reason'
KEY_OPTION = 'option'
KEY_ID = 'id'
Answer = namedtuple( 'Answer', [KEY_CONTENT, KEY_REASON, KEY_ID] )


def answerIsEmpty( content, reason ):  return ( content in [None, ''] ) and ( reason in [None, ''] )  # Do not treat zero as empty


OptionAndReason = namedtuple( 'OptionAndReason', ['optionId', 'reason'] )




if conf.IS_CLOUD:
    from google.appengine.ext import ndb

    # Storage record user's answers to all questions in a survey -- supplemented by proposal-reason records
    # map{  (survey x user)  ->  tree{ questionId/option... -> answer:(content, reason) }  }
    class SurveyAnswers( ndb.Model ):

        # Key
        surveyId = ndb.StringProperty()
        userId = ndb.StringProperty()
        
        answers = ndb.JsonProperty( default={}, indexed=False )  # map{ questionId -> answer }

        ######################################################################################
        # Construction and retrieval methods

        @staticmethod
        def retrieveOrCreate( surveyId, userId ):  return SurveyAnswers.retrieve(surveyId, userId) or SurveyAnswers.create(surveyId, userId)

        @staticmethod
        def create( surveyId, userId ):  return SurveyAnswers( id=toKeyId(surveyId, userId), surveyId=surveyId, userId=userId )

        @staticmethod
        def retrieve( surveyId, userId ):  return SurveyAnswers.get_by_id( toKeyId(surveyId, userId) )



###############################################################################################
# Database

if not conf.IS_CLOUD:

    TABLE_NAME = 'user_answers'
    storage.databaseInitialize( f"""
        create table if not exists {TABLE_NAME} (
         id  varchar(144)  not null ,
         surveyId  int  not null ,
         userId  varchar({user.const.ID_COOKIE_LENGTH})  not null ,
         answers  json  not null  default ('{{}}') ,

         foreign key (surveyId) references {multi.survey.TABLE_NAME}(id) ,
         primary key (surveyId, userId)
        )
    """ )
    # answers : map{ questionId -> answer }
    # TO DO:  Remove unnecessary id column, instead use surveyId x userId as primary key

    def retrieveOrCreateDatabase( surveyId, userId ):
        return retrieveDatabase(surveyId, userId) or createDatabase(surveyId, userId)

    def createDatabase( surveyId, userId ):
        id = toKeyId(surveyId, userId)
        record = storage.RecordDatabase.create( 
            table=TABLE_NAME, id=id, fields={'surveyId':surveyId, 'userId':userId, 'answers':{}}, jsons=['answers'] )
        logging.warning(LogMessage( 'record=', record ))
        record.put()
        return record

    def retrieveDatabase( surveyId, userId ):
        record = storage.RecordDatabase.retrieve( TABLE_NAME, toKeyId(surveyId, userId) )
        logging.warning(LogMessage( 'record=', record ))
        return record



###############################################################################################
# Uniform interface

def retrieveOrCreate( surveyId, userId ):
    if conf.IS_CLOUD:  return SurveyAnswers.retrieveOrCreate( surveyId, userId )
    else:              return retrieveOrCreateDatabase( surveyId, userId )

def toKeyId( surveyId, userId ):  return '{}-{}'.format( surveyId, userId )

def toClient( record, userId ):
    return record.answers


# Assume rank and answer are 1-based, but ranking is zero-based
def setRanking( record, questionId, optionsAllowed, ranking, optionId, rank, reason ):
    # Could store rank answers in an array to ensure ordering
    # But keeping the standard map{ option-ID -> answer, reason } may have benefits like storing a reason without a rank

    # Initially, every option has a default rank in display, no visible gaps
    # User probably wants to find options and move them up to the top ranks, pushing down collided options, leaving no gaps
    # So always move collided options in the direction of moved option

    # Do not have to condense rank, since user may have only ranked an option to a middle rank

    # Better for client to send all {rank, option}, since without reasons, user cannot distinguish un/ranked options?
    #  - Client has to do reordering logic
    #  + No gaps ever
    #  + Simpler server logic
    #  + Simpler client logic without merging answers and random order?  No, still needed for incomplete answers / stale options
    #  + No storing answers for stale options
    #  + Client data validity can still be checked by server
    #  + Option order is more stable for user, only randomized on first view

    # Ensure question-answers exist
    if not record.answers:  record.answers = { }
    if questionId not in record.answers:  record.answers[ questionId ] = { }
    optionToAnswer = record.answers[ questionId ]
    logging.debug(LogMessage( 'optionToAnswer=', optionToAnswer ))

    # Remove option from old rank
    ranking = [ o  for o in ranking  if (o != optionId) and (o in optionsAllowed) ]
    logging.debug( LogMessage('ranking=', ranking) )

    # Insert option to new rank
    ranking.insert( rank-1, optionId )
    logging.debug( LogMessage('ranking=', ranking) )

    # Null out old ranks, but keep old reasons
    for o,a in optionToAnswer.items():
        a[ KEY_CONTENT ] = None
    logging.debug( LogMessage('optionToAnswer=', optionToAnswer) )
    # Merge ranks back into map{ option-ID -> rank, reason }
    for r,o in enumerate( ranking ):
        if o in optionToAnswer:  optionToAnswer[ o ][ KEY_CONTENT ] = str( r + 1 )
        else:  optionToAnswer[ o ] = { KEY_CONTENT:str(r+1), KEY_REASON:None }
    logging.debug( LogMessage('optionToAnswer=', optionToAnswer) )

    optionToAnswer[ optionId ][ KEY_REASON ] = reason
    logging.debug( LogMessage('optionToAnswer=', optionToAnswer) )
    __touchAnswers( record )


def questionHasAnswer( record, questionId ):
    optionToAnswer = getQuestionAnswers( record, questionId )
    if optionToAnswer:
        for o,a in optionToAnswer.items():
            if a  and  ( type(a) == dict )  and  not answerIsEmpty( a.get(KEY_CONTENT, None), a.get(KEY_REASON, None) ):
                return True
    return False

def getQuestionAnswers( record, questionId ):
    return record.answers.get( questionId, None )  if record.answers  else None

# subkeys are strings
def getAnswer( record, subkeys ):
    subkeyMap = getSubtree( record, subkeys )
    if subkeyMap:  return Answer( subkeyMap.get(KEY_CONTENT, None) , subkeyMap.get(KEY_REASON, None) , subkeyMap.get(KEY_ID, None) )
    return Answer( None, None, None )

def getSubtree( record, subkeys ):
    if not record.answers:  return None

    subkeyMap = record.answers
    for subkey in subkeys:
        subkeyMap = subkeyMap.get( subkey, None )
        if subkeyMap is None:  return None

    return subkeyMap

def setAnswer( record, subkeys, answerContent, reason, setId=False, id=None ):
    if not record.answers:  record.answers = { }

    subkeyMap = record.answers
    for subkey in subkeys:
        if not subkey in subkeyMap:
            subkeyMap[ subkey ] = { }
        subkeyMap = subkeyMap[ subkey ]

    subkeyMap[ KEY_CONTENT ] = answerContent
    subkeyMap[ KEY_REASON ] = reason

    if setId and not subkeyMap.get( KEY_ID, None ):
        newId = id
        if newId is None:
            parent = getSubtree( record, subkeys[0:-1] )
            existingIds = [ a.get(KEY_ID, -1)  for o,a in parent.items() ]
            newId = 1 + max( existingIds )  if existingIds  else 0
        subkeyMap[ KEY_ID ] = newId

    __touchAnswers( record )
    return subkeyMap

def removeAnswer( record, subkeys ):
    oldAnswer = getAnswer( record, subkeys )
    parent = getSubtree( record, subkeys[0:-1] )
    if parent:  parent.pop( subkeys[-1], None )
    __touchAnswers( record )
    return oldAnswer

def budgetSum( record, questionId ):
    if not record.answers:  return 0
    budgetItemToAnswer = record.answers.get( questionId, None )
    if not budgetItemToAnswer:  return 0
    return sum(  int( amountAndReason[KEY_CONTENT] )  for budgetItem, amountAndReason in budgetItemToAnswer.items()  )

def numItems( record, questionId ):
    if not record.answers:  return 0
    itemToAnswer = record.answers.get( questionId, None )
    return len( itemToAnswer )  if itemToAnswer  else 0


# Returns null if answer & reason unchanged
def updateAnswer( userId, surveyId, subkeys, answerContent, reason ):
    logging.warning(LogMessage('userId=', userId, 'surveyId=', surveyId, 'subkeys=', subkeys))

    # Retrieve user-survey-answer
    userVoteRecord = retrieveOrCreate( surveyId, userId )
    logging.warning(LogMessage('userVoteRecord=', userVoteRecord))

    questionHadAnswer = questionHasAnswer( userVoteRecord, subkeys[0].value )
    logging.warning(LogMessage('questionHadAnswer=', questionHadAnswer))

    # Store answer in user-survey-answers, only if answer changed
    answerOld = getAnswer( userVoteRecord, multi.voteAggregates.SubKey.subkeysToStrings(subkeys) )
    logging.warning(LogMessage('answerOld=', answerOld))

    if ( answerOld.content == answerContent ) and ( answerOld.reason == reason ):  return None, None, None
    setAnswer( userVoteRecord, multi.voteAggregates.SubKey.subkeysToStrings(subkeys), answerContent, reason )
    userVoteRecord.put()
    logging.warning(LogMessage('userVoteRecord=', userVoteRecord))

    return userVoteRecord, answerOld, questionHadAnswer


def __touchAnswers( record ):
    if not conf.IS_CLOUD:  record.touchField( 'answers' )

