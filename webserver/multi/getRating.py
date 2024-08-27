# HTTP service endpoints

# Import external modules
import json
import logging
import os
# Import app modules
from multi.configMulti import conf
import httpServer
from httpServer import app
import linkKey
import multi.content
from multi.shared import toProposalId
from multi.shared import reasonForClient, proposalForClient
from multi import survey
import storage
import text
from text import LogMessage
import user
import multi.userAnswers
from multi import voteAggregates
from multi.voteAggregates import SubKey


################################################################################################
# Methods: shared

def parseInputs( httpRequest, httpResponse, inputData=None, idRequired=False ):
    httpRequestId = os.environ.get( conf.REQUEST_LOG_ID )
    responseData = { 'success':False, 'httpRequestId':httpRequestId }
    errorMessage = None
    if inputData is None:  inputData = httpRequest.getUrlParams()

    cookieData = httpServer.validate( httpRequest, inputData, responseData, httpResponse, idRequired=idRequired, outputError=False )
    if idRequired and not cookieData.valid():  errorMessage = conf.NO_COOKIE
    userId = cookieData.id()
    return responseData, cookieData, userId, errorMessage


def retrieveLink( linkKeyStr, enforceLogin=False, errorMessage=None ):
    # Pass-through error message
    if errorMessage:  return None, None, errorMessage

    # Retrieve and check linkKey
    linkKeyRecord = linkKey.get_by_id( linkKeyStr )
    if (linkKeyRecord is None) or (linkKeyRecord.destinationType != conf.MULTI_SURVEY_CLASS_NAME):  return linkKeyRecord, None, conf.BAD_LINK
    surveyId = linkKeyRecord.destinationId
    logging.warning(LogMessage( 'linkKeyRecord=', linkKeyRecord ))

    # Enforcing login requirement because the search is expensive and part of a write interaction
    if enforceLogin  and  linkKeyRecord.loginRequired  and  not cookieData.loginId:  return linkKeyRecord, surveyId, conf.NO_LOGIN

    return linkKeyRecord, surveyId, None



################################################################################################
# Methods to serve current user's answers

# For showing rating-question result ratings
@app.get( r'/multi/userAnswers/<alphanumeric:linkKeyStr>' )
def userAnswersToMultiQuestionSurvey( linkKeyStr ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    # Retrieve link
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=False )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve user answers to survey
    answersRecord = multi.userAnswers.retrieveOrCreate( surveyId, userId )
    logging.warning(LogMessage( 'answersRecord=', answersRecord ))

    # Send answers to client
    answersForDisplay = multi.userAnswers.toClient( answersRecord, userId )
    responseData.update(  { 'success':True , 'answers':answersForDisplay }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )


################################################################################################
# Methods to serve question answer suggestions

# Use POST for privacy of user's answer-input
@app.post( r'/multi/getRatingReasonsForPrefix' )
def ratingReasonsForPrefix( ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    inputData = httpRequest.postJsonData()
    logging.debug(LogMessage('ratingReasonsForPrefix', 'inputData=', inputData))

    linkKeyStr = inputData['linkKey']
    questionId = str( inputData['questionId'] )
    optionId = str( inputData['optionId'] )
    logging.debug(LogMessage('ratingReasonsForPrefix', 'linkKeyStr=', linkKeyStr, 'questionId=', questionId, 'optionId=', optionId))

    reasonStart = text.standardizeContent( inputData.get( 'reasonStart', None ) )
    logging.debug(LogMessage('ratingReasonsForPrefix', 'reasonStart=', reasonStart))

    currentRating = inputData.get( 'rating', None )
    currentRating =  None  if currentRating in ['', None]  else int( currentRating )
    logging.debug(LogMessage('ratingReasonsForPrefix', 'currentRating=', currentRating))

    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, inputData=inputData, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    # Enforcing login requirement on this read-only GET call, because the search is expensive, and is part of a write interaction
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve survey record
    surveyRecord = survey.retrieve( surveyId )
    if surveyRecord is None:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.BAD_LINK )
    # Check that survey is active and question is part of survey, to reduce unnecessary expensive queries
    if not survey.questionIdExists( surveyRecord, questionId ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='questionId invalid' )
    if surveyRecord.freezeUserInput:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.FROZEN )
    if ( currentRating is not None ) and ( not survey.isAnswerInBounds(surveyRecord, questionId, currentRating) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.OUT_OF_RANGE )

    # Retrieve best suggested ratings & reasons for this question option
    isBudget = ( survey.getQuestionType(surveyRecord, questionId) == multi.survey.TYPE_BUDGET )  # Budget option-id is hash of content
    ratingsAndReasons = voteAggregates.retrieveTopNumericAnswersAndReasons( surveyId, questionId, optionId, answerNumber=currentRating, reasonStart=reasonStart, isBudget=isBudget )
    logging.warning(LogMessage('ratingReasonsForPrefix', 'ratingsAndReasons=', ratingsAndReasons))

    # Send reasons to client
    reasonsForDisplay = [ multi.voteAggregates.toClient(r, userId) for r in ratingsAndReasons ]
    responseData.update(  { 'success':True , 'suggestions':reasonsForDisplay }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )


# Use POST for privacy of user's answer-input
@app.post( r'/multi/answersAndReasonsForPrefix' )
def answersAndReasonsForPrefix( ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    inputData = httpRequest.postJsonData()
    logging.debug(LogMessage('answersAndReasonsForPrefix', 'inputData=', inputData))

    linkKeyStr = inputData['linkKey']
    questionId = inputData['questionId']
    logging.debug(LogMessage('answersAndReasonsForPrefix', 'linkKeyStr=', linkKeyStr, 'questionId=', questionId))

    inputStart = text.standardizeContent( inputData.get( 'inputStart', None ) )
    logging.debug(LogMessage('answersAndReasonsForPrefix', 'inputStart=', inputStart))

    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, inputData=inputData, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    # Enforcing login requirement on this read-only GET call, because the search is expensive, and is part of a write interaction
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve survey record
    surveyRecord = survey.retrieve( surveyId )
    if surveyRecord is None:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.BAD_LINK )
    # Check that survey is active and question is part of survey, to reduce unnecessary expensive queries
    if not survey.questionIdExists( surveyRecord, questionId ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='questionId invalid' )
    if surveyRecord.freezeUserInput:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.FROZEN )

    # Retrieve best suggested answers & reasons for this question option
    answersAndReasons = None
    if ( survey.getQuestionType(surveyRecord, questionId) == multi.survey.TYPE_BUDGET ):
        answersAndReasons = voteAggregates.retrieveTopAllocationsAndReasons( surveyId, questionId, inputText=inputStart )
    else:
        answersAndReasons = voteAggregates.retrieveTopAnswersAndReasons( surveyId, questionId, inputText=inputStart )
    logging.warning(LogMessage('answersAndReasonsForPrefix', 'answersAndReasons=', answersAndReasons))

    # Send reasons to client
    reasonsForDisplay = [ multi.voteAggregates.toClient(r, userId) for r in answersAndReasons ]
    responseData.update(  { 'success':True , 'suggestions':reasonsForDisplay }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )



# Use POST for privacy of user's answer-input
@app.post( r'/multi/problemsForPrefix' )
def problemsForPrefix( ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    inputData = httpRequest.postJsonData()
    logging.debug(LogMessage('inputData=', inputData))

    linkKeyStr = inputData['linkKey']
    questionId = inputData['questionId']
    logging.debug(LogMessage('linkKeyStr=', linkKeyStr, 'questionId=', questionId))

    inputStart = text.standardizeContent( inputData.get( 'inputStart', None ) )
    logging.debug(LogMessage('inputStart=', inputStart))

    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, inputData=inputData, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    # Enforcing login requirement on this read-only GET call, because the search is expensive, and is part of a write interaction
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve survey record
    surveyRecord = survey.retrieve( surveyId )
    if surveyRecord is None:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.BAD_LINK )
    # Check that survey is active and question is part of survey, to reduce unnecessary expensive queries
    if not survey.questionIdExists( surveyRecord, questionId ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='questionId invalid' )
    if surveyRecord.freezeUserInput:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.FROZEN )

    # Retrieve best suggested problems for this proposal
    contentRecords = multi.content.retrieveTopMatchingProblems( surveyId, questionId, inputStart )
    logging.debug(LogMessage('contentRecords=', contentRecords))

    # Send reasons to client
    contentForDisplay = [ multi.content.toClient(r, userId) for r in contentRecords ]  if contentRecords  else []
    responseData.update(  { 'success':True , 'suggestions':contentForDisplay }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )

# Use POST for privacy of user's answer-input
@app.post( r'/multi/solutionsForPrefix' )
def solutionsForPrefix( ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    inputData = httpRequest.postJsonData()
    logging.debug(LogMessage('inputData=', inputData))

    linkKeyStr = inputData['linkKey']
    questionId = inputData['questionId']
    problemId = inputData.get( 'problemId', None )
    problemId = None  if problemId is None  else int( problemId )
    logging.debug(LogMessage('linkKeyStr=', linkKeyStr, 'questionId=', questionId, 'problemId=', problemId))

    inputStart = text.standardizeContent( inputData.get( 'inputStart', None ) )
    logging.debug(LogMessage('inputStart=', inputStart))

    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, inputData=inputData, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    # Enforcing login requirement on this read-only GET call, because the search is expensive, and is part of a write interaction
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve survey record
    surveyRecord = survey.retrieve( surveyId )
    if surveyRecord is None:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.BAD_LINK )
    # Check that survey is active and question is part of survey, to reduce unnecessary expensive queries
    if not survey.questionIdExists( surveyRecord, questionId ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='questionId invalid' )
    if surveyRecord.freezeUserInput:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.FROZEN )

    # Retrieve best suggested solutions for this proposal
    contentRecords = multi.content.retrieveTopMatchingSolutions( surveyId, questionId, problemId, inputStart )
    logging.debug(LogMessage('contentRecords=', contentRecords))

    # Send reasons to client
    contentForDisplay = [ multi.content.toClient(r, userId) for r in contentRecords ]  if contentRecords  else []
    responseData.update(  { 'success':True , 'suggestions':contentForDisplay }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )

# Use POST for privacy of user's answer-input
@app.post( r'/multi/solutionReasonsForPrefix' )
def solutionReasonsForPrefix( ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    inputData = httpRequest.postJsonData()
    logging.debug(LogMessage('inputData=', inputData))

    linkKeyStr = inputData['linkKey']
    questionId = inputData['questionId']
    problemId = inputData.get( 'problemId', None )
    problemId = None  if problemId is None  else int( problemId )
    solutionId = inputData.get( 'solutionId', None )
    solutionId = None  if solutionId is None  else int( solutionId )
    logging.debug(LogMessage('linkKeyStr=', linkKeyStr, 'questionId=', questionId, 'problemId=', problemId, 'solutionId=', solutionId))

    inputStart = text.standardizeContent( inputData.get( 'inputStart', None ) )
    logging.debug(LogMessage('inputStart=', inputStart))

    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, inputData=inputData, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    # Enforcing login requirement on this read-only GET call, because the search is expensive, and is part of a write interaction
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve survey record
    surveyRecord = survey.retrieve( surveyId )
    if surveyRecord is None:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.BAD_LINK )
    # Check that survey is active and question is part of survey, to reduce unnecessary expensive queries
    if not survey.questionIdExists( surveyRecord, questionId ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='questionId invalid' )
    if surveyRecord.freezeUserInput:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.FROZEN )

    # Retrieve best suggested solutions for this proposal
    contentRecords = multi.content.retrieveTopMatchingReasons( surveyId, questionId, problemId, solutionId, inputStart )
    logging.debug(LogMessage('contentRecords=', contentRecords))

    # Send reasons to client
    contentForDisplay = [ multi.content.toClient(r, userId) for r in contentRecords ]  if contentRecords  else []
    responseData.update(  { 'success':True , 'suggestions':contentForDisplay }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )



################################################################################################
# Methods to serve question results

# For showing rating-question result ratings
@app.get( r'/multi/questionOptionRatings/<alphanumeric:linkKeyStr>/<alphanumeric:questionId>' )
def questionOptionTopRatings( linkKeyStr, questionId ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=False )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve survey
    surveyRecord = survey.retrieve( surveyId )
    logging.warning(LogMessage( 'surveyRecord=', surveyRecord ))
    optionIds = survey.getQuestionOptionIds( surveyRecord, questionId )

    # Collect map{  optionId -> series[ struct{rating, votes} ]  }
    optionToTopRatings = { }
    optionToRatingDistribution = { }
    for optionId in optionIds:
        # Retrieve child-distribution from parent aggregate-record
        childToVotes, averageChild, medianChild = voteAggregates.retrieveOptionVoteAgg( surveyId, questionId, optionId )
        logging.warning(LogMessage('childToVotes=', childToVotes))
        if childToVotes:
            optionToTopRatings[ optionId ] = [  { 'rating':child, 'votes':votes }  for child,votes in childToVotes.items()  ]
            optionToRatingDistribution[ optionId ] = { 'average':averageChild , 'median':medianChild }

    # Retrieve total number of voters for question
    questionVotesForClient = None
    if survey.getQuestionType( surveyRecord, questionId ) == survey.TYPE_CHECKLIST:
        questionVotes = voteAggregates.retrieveQuestionVoteAgg( surveyId, questionId )
        logging.warning(LogMessage('questionVotes=', questionVotes))
        if questionVotes:
            questionVotesForClient = { 'voters':questionVotes.voteCount }

    # Send options to client
    responseData.update(  { 'success':True , 'options':optionToTopRatings , 'optionToRatingDistribution':optionToRatingDistribution, 
        'question':questionVotesForClient }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )

# For showing rating-question result reasons
@app.get( r'/multi/ratingTopReasons/<alphanumeric:linkKeyStr>/<alphanumeric:questionId>/<alphanumeric:optionId>/<int(signed=True):rating>' )
def ratingTopReasons( linkKeyStr, questionId, optionId, rating ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    if ( rating < conf.MIN_RATING ) or ( conf.MAX_RATING < rating ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='Invalid rating' )

    cursor = storage.browserToStorageCursor( httpRequest.getUrlParam('cursor', None) )

    # Retrieve link
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=False )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve top option rating reasons
    reasonVoteCounts, cursor, more = voteAggregates.retrieveRatingQuestionTopReasons( surveyId, questionId, optionId, rating, cursor=cursor, maxRecords=5 )
    logging.warning(LogMessage('reasonVoteCounts=', reasonVoteCounts))

    # Send reasons to client
    cursor = storage.storageToBrowserCursor( cursor )
    reasonsForDisplay = [ {'reasonId':r.id, 'reason':r.content, 'votes':r.votes}  for r in reasonVoteCounts ]
    responseData.update(  { 'success':True , 'reasons':reasonsForDisplay , 'cursor':cursor , 'more':more }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )



# For showing text-question results
@app.get( r'/multi/questionTopAnswers/<alphanumeric:linkKeyStr>/<alphanumeric:questionId>' )
def questionTopAnswers( linkKeyStr, questionId ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    
    cursor = storage.browserToStorageCursor( httpRequest.getUrlParam('cursor', None) )
    
    # Retrieve link
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=False )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve top-voted answers
    answerVoteCounts, cursor, more = voteAggregates.retrieveTextQuestionTopAnswers( surveyId, questionId, maxRecords=5, cursor=cursor )
    logging.debug(LogMessage('answerVoteCounts=', answerVoteCounts))

    # Send reasons to client
    cursor = storage.storageToBrowserCursor( cursor )
    answersForDisplay = [ {'answerId':a.id, 'answer':a.content, 'votes':a.votes}  for a in answerVoteCounts ]  if answerVoteCounts  else []
    responseData.update(  { 'success':True , 'answers':answersForDisplay , 'cursor':cursor, 'more':more }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )


@app.get( r'/multi/questionAnswerTopReasons/<alphanumeric:linkKeyStr>/<alphanumeric:questionId>/<alphanumeric:answerId>' )
def questionAnswerTopReasons( linkKeyStr, questionId, answerId ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=False )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve top-voted answers
    reasonVoteCounts, cursor, more = voteAggregates.retrieveTextQuestionTopReasons( surveyId, questionId, answerId, maxRecords=5 )
    logging.debug(LogMessage('reasonVoteCounts=', reasonVoteCounts))

    # Send reasons to client
    reasonsForDisplay = [ {'reasonId':r.id, 'reason':r.content, 'votes':r.votes}  for r in reasonVoteCounts ]
    responseData.update(  { 'success':True , 'reasons':reasonsForDisplay }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )



# For showing request-for-problems question results
@app.get( r'/multi/topProblems/<alphanumeric:linkKeyStr>/<alphanumeric:questionId>' )
def topProblems( linkKeyStr, questionId ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=False )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve top un/voted reasons, async
    contentRecords, cursor, more = multi.content.retrieveTopProblems( surveyId, questionId, maxRecords=5 )
    logging.warning(LogMessage('contentRecords=', contentRecords))

    # Send reasons to client
    contentForDisplay = [ multi.content.toClient(r, userId) for r in contentRecords ]  if contentRecords  else []
    responseData.update(  { 'success':True , 'problems':contentForDisplay }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )

@app.get( r'/multi/topSolutions/<alphanumeric:linkKeyStr>/<alphanumeric:questionId>/<alphanumeric:problemId>' )
@app.get( r'/multi/topSolutions/<alphanumeric:linkKeyStr>/<alphanumeric:questionId>' )
def topSolutions( linkKeyStr, questionId, problemId=None ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=False )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve top net-pro solutions, async
    contentRecords, cursor, more = multi.content.retrieveTopSolutions( surveyId, questionId, problemId, maxRecords=5 )
    logging.debug(LogMessage('contentRecords=', contentRecords))

    # Send reasons to client
    contentForDisplay = [ multi.content.toClient(r, userId) for r in contentRecords ]  if contentRecords  else []
    responseData.update(  { 'success':True , 'solutions':contentForDisplay }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )

@app.get( r'/multi/topSolutionReasons/<alphanumeric:linkKeyStr>/<alphanumeric:questionId>/<alphanumeric:problemId>/<alphanumeric:solutionId>' )
def topSolutionReasons( linkKeyStr, questionId, solutionId, problemId=None ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    if ( problemId == 'x' ):  problemId = None
    if ( solutionId == 'x' ):  solutionId = None

    cursorPro = storage.browserToStorageCursor( httpRequest.getUrlParam('cursorPro', None) )
    cursorCon = storage.browserToStorageCursor( httpRequest.getUrlParam('cursorCon', None) )

    # Retrieve link
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=False )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve top un/voted reasons, async
    proRecords, cursorPro, cursorProMore = multi.content.retrieveTopReasons( surveyId, questionId, problemId, solutionId, proOrCon=conf.PRO, cursor=cursorPro, maxRecords=3 )
    logging.debug(LogMessage('proRecords=', proRecords))
    conRecords, cursorCon, cursorConMore = multi.content.retrieveTopReasons( surveyId, questionId, problemId, solutionId, proOrCon=conf.CON, cursor=cursorCon, maxRecords=3 )
    logging.debug(LogMessage('conRecords=', conRecords))

    # Send reasons to client
    prosForDisplay = [ multi.content.toClient(r, userId) for r in proRecords ]  if proRecords  else []
    consForDisplay = [ multi.content.toClient(r, userId) for r in conRecords ]  if conRecords  else []
    responseData.update(  { 'success':True , 'pros':prosForDisplay , 'cons':consForDisplay, 'cursorPro':cursorPro, 'cursorCon':cursorCon,
        'cursorProMore':cursorProMore, 'cursorConMore':cursorConMore
    }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )




# For showing budget-question result items
@app.get( r'/multi/budgetTopItems/<alphanumeric:linkKeyStr>/<alphanumeric:questionId>' )
def budgetTopItems( linkKeyStr, questionId ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=False )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve enough top-voted allocations to fill a budget
    answerVoteCounts, cursor, more = voteAggregates.retrieveBudgetQuestionTopItems( surveyId, questionId, maxRecords=20 )
    logging.debug(LogMessage('answerVoteCounts=', answerVoteCounts))

    # If allocations sum to more than 100% of budget, truncate
    allocationsUnderLimit = []
    sum = 0
    for a in answerVoteCounts:
        amount = a.median or 0
        sum += amount
        excess = (sum - 100)
        remainingAmount = amount - excess
        resultAmount = amount  if ( sum <= 100 )  else remainingAmount
        logging.debug(LogMessage('amount=', amount, 'sum=', sum, 'excess=', excess, 'resultAmount=', resultAmount))
        allocationsUnderLimit.append( {'answerId':a.id, 'answer':a.content, 'votes':a.votes, 'medianSize':resultAmount} )
        if ( 100 <= sum ):  break

    # Send allocations to client
    responseData.update(  { 'success':True , 'answers':allocationsUnderLimit }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )

# For showing budget-item result reasons
@app.get( r'/multi/budgetItemTopReasons/<alphanumeric:linkKeyStr>/<alphanumeric:questionId>/<alphanumeric:itemId>' )
def budgetItemTopReasons( linkKeyStr, questionId, itemId ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=False )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve top-voted answers
    reasonVoteCounts, cursor, more = voteAggregates.retrieveBudgetQuestionTopReasons( surveyId, questionId, itemId, maxRecords=5 )
    logging.debug(LogMessage('reasonVoteCounts=', reasonVoteCounts))

    # Send reasons to client
    reasonsForDisplay = [  
        { 'reasonId':a.id, 'reason':a.content, 'votes':a.votes, 'amount':a.allocation }  for a in reasonVoteCounts  ]
    responseData.update(  { 'success':True , 'reasons':reasonsForDisplay }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )



# For showing list-question result items
@app.get( r'/multi/listTopItems/<alphanumeric:linkKeyStr>/<alphanumeric:questionId>' )
def listTopItems( linkKeyStr, questionId ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=False )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve top-voted list-items
    answerVoteCounts, cursor, more = voteAggregates.retrieveListQuestionTopAnswers( surveyId, questionId, maxRecords=10 )
    logging.debug(LogMessage('answerVoteCounts=', answerVoteCounts))

    # Send allocations to client
    itemsForClient = [ {'answerId':a.id, 'answer':a.content, 'votes':a.votes}  for a in answerVoteCounts ]
    responseData.update(  { 'success':True , 'answers':itemsForClient }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )

# For showing list-item result reasons
@app.get( r'/multi/listItemTopReasons/<alphanumeric:linkKeyStr>/<alphanumeric:questionId>/<alphanumeric:itemId>' )
def listItemTopReasons( linkKeyStr, questionId, itemId ):
    # Collect inputs
    httpRequest, httpResponse = httpServer.requestAndResponse()
    responseData, cookieData, userId, errorMessage = parseInputs( httpRequest, httpResponse, idRequired=True )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve link
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyStr, enforceLogin=False )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    # Retrieve top-voted answers
    reasonVoteCounts, cursor, more = voteAggregates.retrieveListQuestionTopReasons( surveyId, questionId, itemId )
    logging.debug(LogMessage('reasonVoteCounts=', reasonVoteCounts))

    # Send reasons to client
    reasonsForDisplay = [  
        { 'reasonId':a.id, 'reason':a.content, 'votes':a.votes }  for a in reasonVoteCounts  ]
    responseData.update(  { 'success':True , 'reasons':reasonsForDisplay }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )

