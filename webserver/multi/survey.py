# Data-record class


from multi.configMulti import conf
# External modules
import json
import logging
import re
# Application modules
import common
import storage
from text import LogMessage
import user


KEY_ID = 'id'
KEY_TYPE = 'type'
KEY_TITLE = 'title'
KEY_DETAIL = 'detail'
KEY_RATING_MIN = 'minRating'
KEY_RATING_MAX = 'maxRating'
KEY_RATING_MIN_LABEL = 'minRatingLabel'
KEY_RATING_MAX_LABEL = 'maxRatingLabel'
KEY_OPTIONS = 'options'
KEY_BUDGET_TOTAL = 'maxTotal'
KEY_MAX_ITEMS = 'maxItems'
KEY_REQUIRE_REASON = 'requireReason'
KEY_IMAGE_ID = 'imageId'

TYPE_INFO = 'info'
TYPE_RATE = 'rate'
TYPE_RANK = 'rank'
TYPE_CHECKLIST = 'checklist'
TYPE_TEXT = 'text'
TYPE_BUDGET = 'budget'
TYPE_LIST = 'list'
TYPE_PROPOSAL = 'proposal'
TYPE_REQUEST_SOLUTIONS = 'solutions'
TYPE_REQUEST_PROBLEMS = 'problems'
QUESTION_TYPES = [ TYPE_INFO, TYPE_RATE, TYPE_RANK, TYPE_CHECKLIST, TYPE_TEXT, TYPE_BUDGET, TYPE_LIST,
    TYPE_PROPOSAL, TYPE_REQUEST_SOLUTIONS, TYPE_REQUEST_PROBLEMS ]



if conf.IS_CLOUD:

    from google.appengine.ext import ndb

    class MultipleQuestionSurvey( ndb.Model ):

        # Content
        title = ndb.StringProperty()
        detail = ndb.StringProperty()
        questions = ndb.JsonProperty( default=[] )  # series[ question:{id, title, detail, type, options?} ] , using array because order matters
        questionInstanceCount = ndb.IntegerProperty( default=0 )
        optionInstanceCount = ndb.IntegerProperty( default=0 )

        # Status
        timeCreated = ndb.IntegerProperty( default=0 )
        creator = ndb.StringProperty()
        freezeUserInput = ndb.BooleanProperty( default=False )
        adminHistory = ndb.JsonProperty( default=[] )  # group[ {text:conf.CHANGE*, time:seconds} ]

        # For cleaning up unused records
        timeModified = ndb.DateTimeProperty( auto_now=True )
        hasResponses = ndb.BooleanProperty( default=False )  # Set when first answer is created by participant


        #########################################################################
        # Methods for surveys

        @staticmethod
        def retrieve( surveyId ):  return MultipleQuestionSurvey.get_by_id( int(surveyId) )


else: # Database

    TABLE_NAME = conf.MULTI_SURVEY_CLASS_NAME
    storage.databaseInitialize( f"""
        create table if not exists {TABLE_NAME} (
         id  int  auto_increment  primary key  not null ,
         title  varchar(128)  not null ,
         detail  text  not null ,
         questions  json  not null  default ('[]') ,
         questionInstanceCount  int  not null  default 0,
         optionInstanceCount  int  not null  default 0,
         timeCreated int  not null,
         creator varchar({user.const.ID_COOKIE_LENGTH})  not null,
         freezeUserInput  boolean  not null  default false,
         timeModified datetime  not null  default current_timestamp  on update current_timestamp,
         adminHistory json  not null  default ('[]') ,
         hasResponses  boolean  not null  default false
        )
    """ )


# adminHistory is a data-structure
def create( *, creator, title, detail, adminHistory, timeCreated ):
    if conf.IS_CLOUD:
        return MultipleQuestionSurvey( creator=creator, title=title, detail=detail, adminHistory=adminHistory, timeCreated=timeCreated )
    else:
        return storage.RecordDatabase.create( table=TABLE_NAME,
            fields={'creator':creator, 'title':title, 'detail':detail, 'adminHistory':adminHistory, 'timeCreated':timeCreated},
            jsons=['adminHistory'], datetimes=['timeModified'] )


def retrieve( surveyId ):
    if conf.IS_CLOUD:  return MultipleQuestionSurvey.get_by_id( int(surveyId) )
    else:              return storage.RecordDatabase.retrieve( TABLE_NAME, surveyId )


def allowEdit( record ):  return not record.hasResponses



#########################################################################
# Methods for questions

def addQuestion( record, title=None, detail=None, type=TYPE_INFO ):
    record.questionInstanceCount += 1
    # Prepend a letter to ID, to ensure it is always treated as a string
    # Do not create ID from hash of content nor from question-position, because these may change
    # Question counter is ok because increments are not contended
    newQuestion = { KEY_ID:'q{}'.format(record.questionInstanceCount), KEY_TITLE:title, KEY_DETAIL:detail, KEY_TYPE:type }
    _setQuestionType( newQuestion, type )
    record.questions.append( newQuestion )
    __touchQuestions( record )
    return newQuestion

def isValidQuestionId( questionId ):  return re.match( r'^q\d+$', questionId )

def questionIdExists( record, questionId ):
    questionsWithId = [ q  for q in record.questions  if q[KEY_ID] == questionId ]
    return ( 0 < len(questionsWithId) )

def getQuestionOptionIds( record, questionId ):
    question = getQuestion( record, questionId )
    return [ q[KEY_ID] for q in question[KEY_OPTIONS] ]  if KEY_OPTIONS in question  else []

def getQuestionType( record, questionId ):
    question = getQuestion( record, questionId )
    return question[ KEY_TYPE ]

def getQuestionRequiresReason( record, questionId ):  return getQuestion( record, questionId ).get( KEY_REQUIRE_REASON, True )

def setQuestionContent( record, questionId, title, detail ):
    question = getQuestion( record, questionId )
    question[ KEY_TITLE ] = title
    question[ KEY_DETAIL ] = detail

def setQuestionImageId( record, questionId, imageId ):
    question = getQuestion( record, questionId )
    question[ KEY_IMAGE_ID ] = imageId

def getQuestionImageId( record, questionId ):
    question = getQuestion( record, questionId )
    return question.get( KEY_IMAGE_ID, None )

def setQuestionType( record, questionId, newType ):
    if newType not in QUESTION_TYPES:  raise KeyError( 'newType not in QUESTION_TYPES' )
    question = getQuestion( record, questionId )
    _setQuestionType( question, newType )
    __touchQuestions( record )

def _setQuestionType( question, newType ):
    question[ KEY_TYPE ] = newType
    if ( newType == TYPE_RATE ):
        if ( question.get(KEY_RATING_MIN, None) == None ):  question[ KEY_RATING_MIN ] = 1
        if ( question.get(KEY_RATING_MAX, None) == None ):  question[ KEY_RATING_MAX ] = 5

def setQuestionRequiresReason( record, questionId, required ):
    getQuestion( record, questionId )[ KEY_REQUIRE_REASON ] = required
    __touchQuestions( record )

def getQuestion( record, questionId ):
    questionsWithId = [ q  for q in record.questions  if q[KEY_ID] == questionId ]
    if ( len(questionsWithId) != 1 ):  raise KeyError(  'Found {} records for questionId={}'.format( len(questionsWithId), questionId )  )
    __touchQuestions( record )   # Inner data may be changed later
    return questionsWithId[ 0 ]

def deleteQuestion( record, questionId ):
    record.questions = [ q  for q in record.questions  if q[KEY_ID] != questionId ]
    __touchQuestions( record )

def getQuestionIds( record ):  return [ q[KEY_ID] for q in record.questions ]

def getIdToQuestion( record ):  return { q[KEY_ID] : q  for q in record.questions }

# Validate answer based on question constraints, for rating, ranking
# Other question-types require different types of validation
#  Example: budget total, existing proposal reason ID
def isAnswerInBounds( record, questionId, answer ):
    if answer is None:  return False
    question = getQuestion( record, questionId )
    questionType = question[ KEY_TYPE ]
    if questionType == TYPE_RATE:
        ratingMin = question[ KEY_RATING_MIN ]
        ratingMax = question[ KEY_RATING_MAX ]
        return ( ratingMin <= answer ) and ( answer <= ratingMax )
    elif questionType == TYPE_RANK:
        # Ranks are 1-based, for less conversion logic
        options = question.get( KEY_OPTIONS, [] )
        return ( 0 < answer ) and ( answer <= len(options) )
    elif questionType == TYPE_CHECKLIST:
        return answer in [ 0, 1 ]
    elif questionType == TYPE_BUDGET:
        return ( 5 <= answer ) and ( answer <= 100 )
    else:
        return False

def __touchQuestions( record ):
    if not conf.IS_CLOUD:  record.touchField( 'questions' )



#########################################################################
# Methods for rating-question options

def addOption( record, questionId, content ):
    record.optionInstanceCount += 1
    question = getQuestion( record, questionId )
    if KEY_OPTIONS not in question:  question[ KEY_OPTIONS ] = []
    newOption = { KEY_ID:'o{}'.format(record.optionInstanceCount) , KEY_TITLE:content }
    question[ KEY_OPTIONS ].append( newOption )
    __touchQuestions( record )
    return newOption

def isValidOptionId( optionId ):  return re.match( r'^o\d+$', optionId )

def setOptionContent( record, questionId, optionId, content ):
    option = getQuestionOption( record, questionId, optionId )
    option[ KEY_TITLE ] = content
    __touchQuestions( record )

def setOptionImageId( record, questionId, optionId, imageId ):
    option = getQuestionOption( record, questionId, optionId )
    option[ KEY_IMAGE_ID ] = imageId
    __touchQuestions( record )

def getOptionImageId( record, questionId, optionId ):
    option = getQuestionOption( record, questionId, optionId )
    return option.get( KEY_IMAGE_ID, None )

def getQuestionOption( record, questionId, optionId ):
    question = getQuestion( record, questionId )
    optionsMatchingId = [ o  for o in question[KEY_OPTIONS]  if o[KEY_ID] == optionId ]
    if ( len(optionsMatchingId) != 1 ):  raise KeyError(  'Found {} records for questionId={} optionId={}'.format( len(optionsMatchingId), questionId, optionId )  )
    return optionsMatchingId[ 0 ]

def reorderQuestionOptions( record, questionId, optionIdsOrdered ):
    question = getQuestion( record, questionId )
    idToOption = { option[KEY_ID] : option  for option in question[KEY_OPTIONS] }
    question[ KEY_OPTIONS ] = [ idToOption[o]  for o in optionIdsOrdered ]
    __touchQuestions( record )


def deleteQuestionOption( record, questionId, optionId ):
    question = getQuestion( record, questionId )
    question[ KEY_OPTIONS ] = [ o  for o in question[KEY_OPTIONS]  if o[KEY_ID] != optionId ]
    __touchQuestions( record )


#########################################################################
# Methods to filter for client display

def toClient( record, userId ):
    jsonData = {
        'id': str( record.key.id() ) ,
        'timeCreated': record.timeCreated ,
        'title': record.title ,
        'detail': record.detail ,
        'mine': ( userId == record.creator ) ,
        'allowEdit': ( userId == record.creator ) and allowEdit( record ) ,
        'freezeUserInput': record.freezeUserInput ,
        'adminHistory': common.decodeChangeHistory( record.adminHistory ) ,
        'questions': [ questionToClient(q, userId)  for q in record.questions ]  if record.questions  else [] ,
    }
    return jsonData

def questionToClient( surveyQuestion, userId ):
    questionType = surveyQuestion.get( KEY_TYPE, None )
    questionStruct = {
        'id': str(  surveyQuestion[ KEY_ID ]  ) ,
        'type': questionType ,
        'title': surveyQuestion.get( KEY_TITLE, None ) ,
        'detail': surveyQuestion.get( KEY_DETAIL, None ) ,
        'options': [ optionToClient(o, userId)  for o in surveyQuestion.get(KEY_OPTIONS, []) ] ,
        'requireReason': surveyQuestion.get( KEY_REQUIRE_REASON, True ) ,
    }

    imageId = surveyQuestion.get( KEY_IMAGE_ID, None )
    if imageId is not None:
        questionStruct['image'] = imageId

    if ( questionType == TYPE_RATE ):
        questionStruct['ratingMin'] = surveyQuestion.get( KEY_RATING_MIN, None )
        questionStruct['ratingMax'] = surveyQuestion.get( KEY_RATING_MAX, None )
        questionStruct['ratingMinLabel'] = surveyQuestion.get( KEY_RATING_MIN_LABEL, None )
        questionStruct['ratingMaxLabel'] = surveyQuestion.get( KEY_RATING_MAX_LABEL, None )
    if ( questionType == TYPE_BUDGET ):
        questionStruct['maxTotal'] = surveyQuestion.get( KEY_BUDGET_TOTAL, None )
    if ( questionType == TYPE_LIST ):
        questionStruct['maxItems'] = surveyQuestion.get( KEY_MAX_ITEMS, 5 )

    return questionStruct

def optionToClient( surveyQuestionOption, userId ):
    jsonData = {
        'id': str(  surveyQuestionOption[ KEY_ID ]  ) ,
        'title': surveyQuestionOption.get( KEY_TITLE, None ) ,
    }

    imageId = surveyQuestionOption.get( KEY_IMAGE_ID, None )
    if imageId is not None:
        jsonData['image'] = imageId

    return jsonData


