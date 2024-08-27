# HTTP service endpoints

# External modules
import json
import logging
import os
# Application modules
from multi.configMulti import conf
import httpServer
from httpServer import app
import linkKey
import multi.content
if conf.IS_CLOUD:  from multi.content import Content
from multi.shared import toProposalId, reasonForClient, proposalForClient
from multi import survey
import multi.userAnswers
import multi.voteAggregates
from multi.voteAggregates import SubKey
import text
from text import LogMessage
import user



################################################################################################
# Methods: shared

def parseInputs( httpRequest, httpResponse ):
    httpRequestId = os.environ.get( conf.REQUEST_LOG_ID )
    responseData = { 'success':False, 'httpRequestId':httpRequestId }
    errorMessage = None

    inputData = httpRequest.postJsonData()
    logging.debug(LogMessage('parseInputs', 'inputData=', inputData))
    cookieData = httpServer.validate( httpRequest, inputData, responseData, httpResponse, outputError=False )
    if not cookieData.valid():  errorMessage = conf.NO_COOKIE
    userId = cookieData.id()
    linkKeyString = inputData.get( 'linkKey', None )
    return responseData, cookieData, userId, inputData, linkKeyString, errorMessage


def retrieveLink( linkKeyString ):
    # Retrieve and check linkKey
    logging.debug(LogMessage('retrieveLink', 'linkKeyString=', linkKeyString))
    if linkKeyString is None:  return None, None, conf.BAD_LINK
    linkKeyRecord = linkKey.get_by_id( linkKeyString )
    logging.debug(LogMessage('retrieveLink', 'linkKeyRecord=', linkKeyRecord))
    if (linkKeyRecord is None) or (linkKeyRecord.destinationType != conf.MULTI_SURVEY_CLASS_NAME):  return linkKeyRecord, None, conf.BAD_LINK

    surveyId = linkKeyRecord.destinationId
    if linkKeyRecord.loginRequired  and  not cookieData.loginId:  return linkKeyRecord, surveyId, conf.NO_LOGIN
    return linkKeyRecord, surveyId, None


def retrieveSurvey( surveyId, userId, errorMessage=None ):
    if errorMessage is not None:  return None, errorMessage  # Pass error through

    surveyRec = survey.retrieve( surveyId )
    logging.debug(LogMessage('userId=', userId, 'surveyRec=', surveyRec))

    if surveyRec is None:  return surveyRec, conf.BAD_LINK
    if surveyRec.freezeUserInput:  return surveyRec, conf.FROZEN

    return surveyRec, None


def storeSurveyResponded( surveyRecord, userId ):
    # Record that survey has responses.  Temporarily contended only for first participants, so no delay.  Idempotent, so no data corruption.
    if ( userId != surveyRecord.creator ) and ( not surveyRecord.hasResponses ):
        surveyRecord.hasResponses = True
        surveyRecord.put()


def reasonExists( proposalId, proOrCon, reasonContent ):
    return reason.Reason.query(
        reason.Reason.proposalId==proposalId ,
        reason.Reason.proOrCon==proOrCon ,
        reason.Reason.content==reasonContent ).fetch( 1 )



################################################################################################
# Methods: HTTP endpoints: answer numeric rating / ranking / checklist questions

@app.post('/multi/rateQuestionOption')
def rateQuestionOption( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']
    optionId = inputData['optionId']
    newRating = inputData.get( 'rating', None )
    newRating = None  if (newRating is None) or (newRating == '')  else int( newRating )

    reasonContent = text.formTextToStored( inputData.get('reason', None) )
    if ( conf.maxLengthReason < len(reasonContent) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    if survey.getQuestionType( surveyRecord, questionId ) not in [ survey.TYPE_RATE ]:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )
    if ( newRating is not None ) and ( not survey.isAnswerInBounds(surveyRecord, questionId, newRating) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.OUT_OF_RANGE )

    if survey.getQuestionRequiresReason( surveyRecord, questionId ) and ( (not reasonContent) or (len(reasonContent) < conf.minLengthReason) ):
        return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )

    storeSurveyResponded( surveyRecord, userId )

    # Record vote
    voteRecord, optionRecord, reasonRecord, questionVotes = multi.voteAggregates.voteRating(
        userId, surveyId, questionId, optionId, newRating, reasonContent )
    if voteRecord is None:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.UNCHANGED )

    # Display updated answers
    responseData.update(  { 'success':True ,
        'answers':multi.userAnswers.toClient(voteRecord, userId) ,
        'option':multi.voteAggregates.toClient(optionRecord, userId) ,
        'reason':multi.voteAggregates.toClient(reasonRecord, userId) ,
    }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )


@app.post('/multi/rankQuestionOptions')
def rankQuestionOptions( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']
    ranking = inputData['ranking']
    optionId = inputData['optionId']
    newRank = inputData.get( 'rank', None )
    newRank = None  if (newRank is None) or (newRank == '')  else int( newRank )   # Assume 1-based rank

    reasonContent = text.formTextToStored( inputData.get('reason', None) )
    if ( conf.maxLengthReason < len(reasonContent) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    if survey.getQuestionType( surveyRecord, questionId ) not in [ survey.TYPE_RANK ]:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )
    if ( newRank is not None ) and ( not survey.isAnswerInBounds(surveyRecord, questionId, newRank) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.OUT_OF_RANGE )

    if survey.getQuestionRequiresReason( surveyRecord, questionId ) and ( (not reasonContent) or (len(reasonContent) < conf.minLengthReason) ):
        return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )

    storeSurveyResponded( surveyRecord, userId )

    # Record vote
    voteRecord = multi.voteAggregates.voteRanking(
        userId, surveyId, questionId, optionId, newRank, reasonContent, ranking=ranking, optionsAllowed=survey.getQuestionOptionIds(surveyRecord, questionId) )
    if voteRecord is None:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.UNCHANGED )

    # Display updated answers
    responseData.update(  { 'success':True , 'answers':multi.userAnswers.toClient(voteRecord, userId) }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )


@app.post('/multi/answerChecklistQuestion') 
def answerChecklistQuestion( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']
    optionId = inputData['optionId']
    newCheckmark = inputData.get( 'rating', None )
    newCheckmark = None  if (newCheckmark is None) or (newCheckmark == '')  else int( newCheckmark )

    reasonContent = text.formTextToStored( inputData.get('reason', None) )
    if ( conf.maxLengthReason < len(reasonContent) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    if survey.getQuestionType( surveyRecord, questionId ) not in [ survey.TYPE_CHECKLIST ]:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )
    if ( newCheckmark is not None ) and ( not survey.isAnswerInBounds(surveyRecord, questionId, newCheckmark) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.OUT_OF_RANGE )

    if survey.getQuestionRequiresReason( surveyRecord, questionId ) and newCheckmark and ( (not reasonContent) or (len(reasonContent) < conf.minLengthReason) ):
        return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )

    storeSurveyResponded( surveyRecord, userId )

    # Record vote
    voteRecord, optionRecord, reasonRecord, questionVotes = multi.voteAggregates.voteChecklist(
        userId, surveyId, questionId, optionId, newCheckmark, reasonContent )
    if voteRecord is None:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.UNCHANGED )

    # Display updated answers
    responseData.update(  { 'success':True ,
        'answers':multi.userAnswers.toClient(voteRecord, userId) ,
        'option':multi.voteAggregates.toClient(optionRecord, userId) ,
        'reason':multi.voteAggregates.toClient(reasonRecord, userId) ,
        'question':multi.voteAggregates.toClient(questionVotes, userId) ,
    }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )



################################################################################################
# Methods: HTTP endpoints: answer text question

@app.post('/multi/answerQuestion') 
def answerTextQuestion( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']
    answer = text.formTextToStored( inputData['answer'] )

    reasonContent = text.formTextToStored( inputData.get('reason', None) )
    if ( conf.maxLengthReason < len(reasonContent) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    if ( survey.getQuestionType(surveyRecord, questionId) != survey.TYPE_TEXT ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )

    if survey.getQuestionRequiresReason( surveyRecord, questionId ) and ( (not reasonContent) or (len(reasonContent) < conf.minLengthReason) ):
        return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )

    storeSurveyResponded( surveyRecord, userId )

    # Record vote
    voteRecord, answerRecord, reasonRecord, questionVotes = multi.voteAggregates.voteText(
        userId, surveyId, questionId, answer, reasonContent )
    if voteRecord is None:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.UNCHANGED )

    # Display updated answers
    responseData.update(  { 'success':True , 'answers':multi.userAnswers.toClient(voteRecord, userId) ,
        'answerVoteAgg':multi.voteAggregates.toClient(answerRecord, userId) ,
        'reason':multi.voteAggregates.toClient(reasonRecord, userId)  ,
    }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )



################################################################################################
# Methods: HTTP endpoints: answer budget question

# Allocations have 3 levels of vote-aggregation:  budget-item, amount, reason
#  Concatenating budget-item + amount would only allow 1 item per budget-question

@app.post('/multi/voteBudgetAllocation')
def voteBudgetAllocation( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']

    amountNew = inputData.get( 'amountNew', None )  # Allow null / zero amount to delete allocation
    amountNew = None  if (amountNew is None) or (amountNew == '')  else int( amountNew )

    # Use old budget-item-content from client, get allocation & reason from user-answers, check for null
    contentOld = text.formTextToStored( inputData.get('contentOld', None) )  # Allow null contentOld to create new allocation
    contentNew = text.formTextToStored( inputData.get('contentNew', None) )
    if amountNew:
        if not contentNew:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )
        if ( conf.maxLengthReason < len(contentNew) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    reasonNew = text.formTextToStored( inputData.get('reasonNew', None) )
    if amountNew:
        if ( conf.maxLengthReason < len(reasonNew) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    if survey.getQuestionType( surveyRecord, questionId ) not in [ survey.TYPE_BUDGET ]:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )
    if amountNew and not survey.isAnswerInBounds(surveyRecord, questionId, amountNew ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.OUT_OF_RANGE )

    if survey.getQuestionRequiresReason( surveyRecord, questionId ) and amountNew and ( (not reasonNew) or (len(reasonNew) < conf.minLengthReason) ):
        return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )

    storeSurveyResponded( surveyRecord, userId )

    # Record vote
    voteRecord, contentAggregateRecord, amountAggregateRecord, reasonAggregateRecord, errorMessage = multi.voteAggregates.voteBudgetItem(
        userId, surveyId, questionId, contentOld, contentNew, amountNew, reasonNew )
    if voteRecord is None:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.UNCHANGED )

    # Display updated answers
    responseData.update(  {
        'success':True ,
        'answers':multi.userAnswers.toClient(voteRecord,  userId ) ,
        'contentAggregateRecord':multi.voteAggregates.toClient(contentAggregateRecord, userId) ,
        'amountAggregateRecord':multi.voteAggregates.toClient(amountAggregateRecord, userId) ,
        'reasonAggregateRecord':multi.voteAggregates.toClient(reasonAggregateRecord, userId) ,
    }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )



################################################################################################
# Methods: HTTP endpoints: answer list question

@app.post('/multi/voteListItem')
def voteListItem( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']

    # Use old item-content from client, get reason from user-answers, check for null
    contentOld = text.formTextToStored( inputData.get('contentOld', None) )  # Allow null contentOld to create new item
    contentNew = text.formTextToStored( inputData.get('contentNew', None) )
    if contentNew and ( conf.maxLengthReason < len(contentNew) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    reasonNew = text.formTextToStored( inputData.get('reasonNew', None) )
    if reasonNew and ( conf.maxLengthReason < len(reasonNew) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    if survey.getQuestionType( surveyRecord, questionId ) != survey.TYPE_LIST:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )

    if contentNew and survey.getQuestionRequiresReason( surveyRecord, questionId ) and ( (not reasonNew) or (len(reasonNew) < conf.minLengthReason) ):
        return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )

    maxItems = survey.getQuestion(surveyRecord,  questionId ).get( survey.KEY_MAX_ITEMS, 5 )
    storeSurveyResponded( surveyRecord, userId )

    # Record vote
    voteRecord, contentAggregateRecord, reasonAggregateRecord, errorMessage = multi.voteAggregates.voteListItem(
        userId, surveyId, questionId, contentOld, contentNew, reasonNew, maxItems=maxItems )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    if voteRecord is None:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.UNCHANGED )

    # Display updated answers
    responseData.update(  {
        'success':True ,
        'answers':multi.userAnswers.toClient(voteRecord,  userId ) ,
        'contentAggregateRecord':multi.voteAggregates.toClient(contentAggregateRecord, userId) ,
        'reasonAggregateRecord':multi.voteAggregates.toClient(reasonAggregateRecord, userId) ,
    }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )



################################################################################################
# Methods: HTTP endpoints: answer request-for-problems question

# Problem / solution / reason and their vote-counts are stored in Content records, to allow content to persist without votes

@app.post('/multi/newProblem') 
def newProblem( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']

    problemContent = text.formTextToStored( inputData.get('problem', None) )
    if (problemContent is None) or ( len(problemContent) < conf.minLengthReason ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )
    if ( conf.maxLengthReason < len(problemContent) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    if ( survey.getQuestionType(surveyRecord, questionId) != survey.TYPE_REQUEST_PROBLEMS ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )

    storeSurveyResponded( surveyRecord, userId )

    # Check for existing identical problem
    if multi.content.exists( surveyId, questionId, [], content=problemContent ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.DUPLICATE )

    # Store new problem record
    problemRecord = multi.content.create( surveyId, questionId, [], content=problemContent, creator=userId )
    problemRecord.put()

    # Send updated answer to client
    responseData.update(  { 'success':True , 'problem':multi.content.toClient(problemRecord, userId) }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )


@app.post('/multi/editProblem') 
def editProblem( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']
    problemId = int( inputData['problemId'] )

    problemContent = text.formTextToStored( inputData.get('problem', None) )
    if (problemContent is None) or ( len(problemContent) < conf.minLengthReason ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )
    if ( conf.maxLengthReason < len(problemContent) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    if ( survey.getQuestionType(surveyRecord, questionId) != survey.TYPE_REQUEST_PROBLEMS ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )

    # Retrieve problem record
    problemRecord = multi.content.retrieve( surveyId, questionId, [], contentId=problemId )
    if not problemRecord:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='problem not found' )
    if ( userId != problemRecord.creator ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.NOT_OWNER )
    if problemRecord.hasResponse:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.HAS_RESPONSES )
    if ( problemRecord.content == problemContent ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.UNCHANGED )

    # Check for existing identical problem
    if multi.content.exists( surveyId, questionId, [], content=problemContent ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.DUPLICATE )

    # Store updated problem record
    multi.content.setContent( problemRecord, problemContent )
    problemRecord.put()

    # Send updated answer to client
    responseData.update(  { 'success':True , 'problem':multi.content.toClient(problemRecord, userId) }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )



@app.post('/multi/newSolution') 
def newSolution( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']
    problemId = inputData.get( 'problemId', None )
    problemId = None  if problemId is None  else int( problemId )

    solutionContent = text.formTextToStored( inputData.get('solution', None) )
    if (solutionContent is None) or ( len(solutionContent) < conf.minLengthReason ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )
    if ( conf.maxLengthReason < len(solutionContent) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    questionType = survey.getQuestionType( surveyRecord, questionId )
    if ( questionType not in [survey.TYPE_REQUEST_PROBLEMS, survey.TYPE_REQUEST_SOLUTIONS] ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )
    if ( questionType == survey.TYPE_REQUEST_PROBLEMS ) and ( problemId is None ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='problemId is null' )

    storeSurveyResponded( surveyRecord, userId )

    # Check that parent problem exists
    problemRecord = None
    if ( problemId is not None ):
        problemRecord = multi.content.retrieve( surveyId, questionId, [], contentId=problemId )
        if not problemRecord:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='problemId not found' )

    # Check for existing identical solution
    if multi.content.exists( surveyId, questionId, [problemId], content=solutionContent ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.DUPLICATE )

    # Store new solution record
    solutionRecord = multi.content.create( surveyId, questionId, [problemId], content=solutionContent, creator=userId )
    solutionRecord.put()

    # Store that problem has responses
    if problemRecord and  not problemRecord.hasResponse:
        problemRecord.hasResponse = True
        problemRecord.put()

    # Send updated answer to client
    responseData.update(  { 'success':True , 'solution':multi.content.toClient(solutionRecord, userId) }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )


@app.post('/multi/editSolution') 
def editSolution( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']
    problemId = inputData.get( 'problemId', None )
    problemId = None  if problemId is None  else int( problemId )
    solutionId = int( inputData['solutionId'] )

    solutionContent = text.formTextToStored( inputData.get('solution', None) )
    if (solutionContent is None) or ( len(solutionContent) < conf.minLengthReason ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )
    if ( conf.maxLengthReason < len(solutionContent) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    questionType = survey.getQuestionType( surveyRecord, questionId )
    if ( questionType not in [survey.TYPE_REQUEST_PROBLEMS, survey.TYPE_REQUEST_SOLUTIONS] ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )
    if ( questionType == survey.TYPE_REQUEST_PROBLEMS ) and ( problemId is None ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='problemId is null' )

    # Retrieve solution record
    solutionRecord = multi.content.retrieve( surveyId, questionId, [problemId], contentId=solutionId )
    if not solutionRecord:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='solution not found' )
    if ( userId != solutionRecord.creator ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.NOT_OWNER )
    if solutionRecord.hasResponse:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.HAS_RESPONSES )
    if ( solutionRecord.content == solutionContent ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.UNCHANGED )

    # Check for existing identical solution
    if multi.content.exists( surveyId, questionId, [problemId], content=solutionContent ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.DUPLICATE )

    # Store updated solution record
    multi.content.setContent( solutionRecord, solutionContent )
    solutionRecord.put()

    # Send updated answer to client
    responseData.update(  { 'success':True , 'solution':multi.content.toClient(solutionRecord, userId) }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )



@app.post('/multi/newSolutionReason')
def newSolutionReason( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']
    problemId = inputData.get( 'problemId', None )
    problemId = None  if problemId is None  else int( problemId )
    solutionId = inputData.get( 'solutionId', None )
    solutionId = None  if solutionId is None  else int( solutionId )

    proOrCon = inputData['proOrCon']
    if ( proOrCon not in [conf.PRO, conf.CON] ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='proOrCon invalid' )

    reasonContent = text.formTextToStored( inputData.get('reason', None) )
    if (reasonContent is None) or ( len(reasonContent) < conf.minLengthReason ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )
    if ( conf.maxLengthReason < len(reasonContent) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    questionType = survey.getQuestionType( surveyRecord, questionId )
    if ( questionType not in [survey.TYPE_REQUEST_PROBLEMS, survey.TYPE_REQUEST_SOLUTIONS, survey.TYPE_PROPOSAL] ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )
    if ( questionType == survey.TYPE_REQUEST_PROBLEMS ) and ( problemId is None ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='problemId is null' )
    if ( questionType == survey.TYPE_REQUEST_SOLUTIONS ) and ( solutionId is None ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='solutionId is null' )

    storeSurveyResponded( surveyRecord, userId )

    # Check that parent solution exists
    solutionRecord = None
    if solutionId:
        solutionRecord = multi.content.retrieve( surveyId, questionId, [problemId], contentId=solutionId )
        if not solutionRecord:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='solutionId not found' )

    # Check for existing identical reason
    if multi.content.exists( surveyId, questionId, [problemId, solutionId], content=reasonContent ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.DUPLICATE )

    # Store new reason record
    reasonRecord = multi.content.create( surveyId, questionId, [problemId, solutionId], proOrCon=proOrCon, content=reasonContent, creator=userId )
    reasonRecord.put()

    # Store that solution has responses
    if solutionRecord  and  not solutionRecord.hasResponse:
        solutionRecord.hasResponse = True
        solutionRecord.put()

    # Send updated answer to client
    responseData.update(  { 'success':True , 'reason':multi.content.toClient(reasonRecord, userId) }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )


@app.post('/multi/editSolutionReason') 
def editSolutionReason( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']
    problemId = inputData.get( 'problemId', None )
    problemId = None  if problemId is None  else int( problemId )
    solutionId = inputData.get( 'solutionId', None )
    solutionId = None  if solutionId is None  else int( solutionId )
    reasonId = int( inputData['reasonId'] )

    reasonContent = text.formTextToStored( inputData.get('reason', None) )
    if (reasonContent is None) or ( len(reasonContent) < conf.minLengthReason ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_SHORT )
    if ( conf.maxLengthReason < len(reasonContent) ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.TOO_LONG )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    questionType = survey.getQuestionType( surveyRecord, questionId )
    if ( questionType not in [survey.TYPE_REQUEST_PROBLEMS, survey.TYPE_REQUEST_SOLUTIONS, survey.TYPE_PROPOSAL] ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )
    if ( questionType == survey.TYPE_REQUEST_PROBLEMS ) and ( problemId is None ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='problemId is null' )
    if ( questionType == survey.TYPE_REQUEST_SOLUTIONS ) and ( solutionId is None ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='solutionId is null' )

    # Retrieve reason record
    reasonRecord = multi.content.retrieve( surveyId, questionId, [problemId, solutionId], contentId=reasonId )
    if not reasonRecord:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='reason not found' )
    if ( userId != reasonRecord.creator ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.NOT_OWNER )
    if reasonRecord.hasResponse:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.HAS_RESPONSES )
    if ( reasonRecord.content == reasonContent ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.UNCHANGED )

    # Check for existing identical reason
    if multi.content.exists( surveyId, questionId, [problemId, solutionId], content=reasonContent ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.DUPLICATE )

    # Store updated reason record
    multi.content.setContent( reasonRecord, reasonContent )
    reasonRecord.put()

    # Send updated answer to client
    responseData.update(  { 'success':True , 'reason':multi.content.toClient(reasonRecord, userId) }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )




@app.post('/multi/voteSolutionReason')
def voteSolutionReason( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    responseData, cookieData, userId, inputData, linkKeyString, errorMessage = parseInputs( httpRequest, httpResponse )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )

    questionId = inputData['questionId']
    problemId = inputData.get( 'problemId', None )
    problemId = None  if problemId is None  else int( problemId )
    solutionId = inputData.get( 'solutionId', None )
    solutionId = None  if solutionId is None  else int( solutionId )
    reasonId = int( inputData['reasonId'] )
    vote = bool( inputData['vote'] )

    # Retrieve link-key & survey records
    linkKeyRecord, surveyId, errorMessage = retrieveLink( linkKeyString )
    surveyRecord, errorMessage = retrieveSurvey( surveyId, userId, errorMessage=errorMessage )
    if errorMessage:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=errorMessage )
    questionType = survey.getQuestionType( surveyRecord, questionId )
    if ( questionType not in [survey.TYPE_REQUEST_PROBLEMS, survey.TYPE_REQUEST_SOLUTIONS, survey.TYPE_PROPOSAL] ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.WRONG_TYPE )
    if ( questionType == survey.TYPE_REQUEST_PROBLEMS ) and ( problemId is None ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='problemId is null' )
    if ( questionType == survey.TYPE_REQUEST_SOLUTIONS ) and ( solutionId is None ):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage='solutionId is null' )

    # Record vote
    userVoteRecord, problemRecord, solutionRecord, reasonRecord, reasonRecordOld = __voteSolutionReason(
        userId, surveyId, questionId, problemId, solutionId, (reasonId if vote else None) )

    if userVoteRecord is None:  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.UNCHANGED )

    # Display updated answers
    responseData.update(  {
        'success':True ,
        'problem': multi.content.toClient( problemRecord,  userId ) ,
        'solution': multi.content.toClient( solutionRecord, userId ) ,
        'reason': multi.content.toClient( reasonRecord,  userId ) ,
        'reasonOld': multi.content.toClient( reasonRecordOld, userId ) ,
        'answers': multi.userAnswers.toClient( userVoteRecord, userId ) ,
    }  )
    return httpServer.outputJson( cookieData, responseData, httpResponse )


def __voteSolutionReason( userId, surveyId, questionId, problemId, solutionId, reasonId ):
    problemId = problemId or 0
    solutionId = solutionId or 0

    userAnswerSubkeys = [ SubKey(str(questionId), isId=True) ]
    if problemId:  userAnswerSubkeys.append( SubKey(str(problemId), isId=True) )
    if solutionId:  userAnswerSubkeys.append( SubKey(str(solutionId), isId=True) )

    if conf.IS_CLOUD:
        userVoteRecord, problemRecord, solutionRecord, reasonRecordNew, reasonRecordOld = __voteSolutionReasonTransaction(
            userId, surveyId, questionId, problemId, solutionId, reasonId, userAnswerSubkeys )

        # Problem score/ranking should be based on maximum solution-score, not sum of solution-scores
        # because this indicates a solvable problem
        #   Otherwise abusers can down-vote a problem by creating & down-voting crappy solutions
        # Update problem max-solution-net-pros, outside vote transaction because it queries all sub-solutions,
        # and it is ok to be stale since it will not immediately be displayed
        if userVoteRecord and ( questionType == survey.TYPE_REQUEST_PROBLEMS ):
            maxSolutionRecords = Content.query( 
                Content.surveyId==str(surveyId), Content.questionId==str(questionId) , Content.parentKey==str(problemId)
                ).order( -Content.voteCount ).fetch( 1 )
            logging.debug(LogMessage('maxSolutionRecords=', maxSolutionRecords))
            if maxSolutionRecords:
                if not problemRecord:  problemRecord = Content.retrieve( surveyId, questionId, [], contentId=problemId )
                if problemRecord:
                    problemRecord.maxChildVotes = maxSolutionRecords[ 0 ].voteCount
                    problemRecord.put()

        return userVoteRecord, problemRecord, solutionRecord, reasonRecordNew, reasonRecordOld

    else:  # Database
        # Store answer in user-survey-answers
        userVoteRecord, answerOld, questionHadAnswer = multi.userAnswers.updateAnswer( userId, surveyId, userAnswerSubkeys, reasonId, None )
        if not userVoteRecord:  return None, None, None, None, None
        # Aggregate user vote
        reasonIdOld = int( answerOld.content )  if ( answerOld and answerOld.content )  else None
        problemRecord, solutionRecord, reasonRecordNew, reasonRecordOld =  multi.content.voteSolutionReasonDatabase(
            userId, surveyId, questionId, problemId, solutionId, reasonId, reasonIdOld )
        return userVoteRecord, problemRecord, solutionRecord, reasonRecordNew, reasonRecordOld


if conf.IS_CLOUD:

    @ndb.transactional(xg=True, retries=conf.MAX_VOTE_RETRY)
    def __voteSolutionReasonTransaction( userId, surveyId, questionId, problemId, solutionId, reasonId, userAnswerSubkeys ):

        logging.debug(LogMessage('userId=', userId, 'surveyId=', surveyId, 'questionId=', questionId, 'problemId=', problemId, 'solutionId=', solutionId, 'reasonId=', reasonId))

        # Store answer in user-survey-answers
        userVoteRecord, answerOld, questionHadAnswer = multi.userAnswers.updateAnswer( userId, surveyId, userAnswerSubkeys, reasonId, None )
        if not userVoteRecord:  return None, None, None, None, None

        reasonIdOld = int( answerOld.content )  if ( answerOld and answerOld.content )  else None

        # Decrement reason losing vote
        reasonRecordOld = None
        if reasonIdOld is not None:
            reasonRecordOld = multi.content.retrieve( surveyId, questionId, [problemId, solutionId], contentId=reasonIdOld )
            logging.debug(LogMessage('reasonRecordOld=', reasonRecordOld))

            if reasonRecordOld and ( 1 <= reasonRecordOld.voteCount ):
                reasonRecordOld.incrementVoteCount( -1 )
                reasonRecordOld.put()

        # Increment reason gaining vote
        reasonRecordNew = None
        if reasonId is not None:
            reasonRecordNew = multi.content.retrieve( surveyId, questionId, [problemId, solutionId], contentId=reasonId )
            logging.debug(LogMessage('reasonRecordNew=', reasonRecordNew))

            reasonRecordNew.incrementVoteCount( 1 )
            reasonRecordNew.hasResponse = True
            logging.debug(LogMessage('reasonRecordNew=', reasonRecordNew))
            reasonRecordNew.put()

        # Increment aggregate pro/con vote-counts for solution and problem, if reason-valence changed
        proOrConOld = reasonRecordOld.proOrCon  if reasonRecordOld  else None
        proOrConNew = reasonRecordNew.proOrCon  if reasonRecordNew  else None
        solutionRecord = None
        problemRecord = None
        if ( proOrConOld != proOrConNew ):
            # Change solution vote count
            solutionRecord = multi.content.retrieve( surveyId, questionId, [problemId], contentId=solutionId )
            multi.content.incrementNumProsOrCons( solutionRecord, proOrConOld, -1 )
            multi.content.incrementNumProsOrCons( solutionRecord, proOrConNew, 1 )
            solutionRecord.put()
            # Change problem vote count
            if problemId:
                problemRecord = multi.content.retrieve( surveyId, questionId, [], contentId=problemId )
                multi.content.incrementNumProsOrCons( problemRecord, proOrConOld, -1 )
                multi.content.incrementNumProsOrCons( problemRecord, proOrConNew, 1 )
                problemRecord.put()

        return userVoteRecord, problemRecord, solutionRecord, reasonRecordNew, reasonRecordOld


