# HTTP service endpoints

# External modules
import flask
import json
import logging
import os
# Application modules
from multi.configMulti import conf
import httpServer
from httpServer import app
import linkKey
from multi import survey
import storage
from text import LogMessage
import user



@app.get( r'/multi/getSurvey/<alphanumeric:linkKeyStr>' )
def getMultiQuestionSurvey( linkKeyStr ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    httpRequestId = os.environ.get( conf.REQUEST_LOG_ID )
    responseData = { 'success':False, 'httpRequestId':httpRequestId }
    cookieData = httpServer.validate( httpRequest, {}, responseData, httpResponse, idRequired=False )
    userId = cookieData.id()
    
    # Retrieve and check linkKey
    linkKeyRecord = linkKey.get_by_id( linkKeyStr )
    if (linkKeyRecord is None) or (linkKeyRecord.destinationType != conf.MULTI_SURVEY_CLASS_NAME):
        return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.BAD_LINK )
    surveyId = linkKeyRecord.destinationId

    # Retrieve survey by ID
    surveyRecord = survey.retrieve( surveyId )
    logging.warning(LogMessage( 'surveyRecord=', surveyRecord ))
    if (surveyRecord is None):  return httpServer.outputJson( cookieData, responseData, httpResponse, errorMessage=conf.BAD_LINK )

    # Filter fields for display
    surveyDisp = survey.toClient( surveyRecord, userId )
    linkKeyDisplay = httpServer.linkKeyToDisplay( linkKeyRecord )
    
    # Store survey to recents in user cookie
    user.storeRecentLinkKey( linkKeyStr, cookieData )

    # Display survey data
    responseData = { 'success':True , 'link':linkKeyDisplay , 'survey':surveyDisp }
    return httpServer.outputJson( cookieData, responseData, httpResponse )



@app.get( r'/image/<alphanumeric:linkKeyStr>/<imageid:imageId>' )
def getSurveyImage( linkKeyStr, imageId ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Retrieve and check linkKey
    linkKeyRecord = linkKey.get_by_id( linkKeyStr )
    logging.warning(LogMessage( 'linkKeyRecord=', linkKeyRecord ))
    if (linkKeyRecord is None) or (linkKeyRecord.destinationType != conf.MULTI_SURVEY_CLASS_NAME):  return '', 404  # Not found
    surveyId = linkKeyRecord.destinationId

    # Retrieve survey
    surveyRecord = survey.retrieve( surveyId )
    logging.warning(LogMessage( 'surveyRecord=', surveyRecord ))
    if (surveyRecord is None):  return '', 404  # Not found
    if not imageId.startswith( f'{surveyId}-' ):  return '', 403   # Forbidden

    # Read image from database
    imageKey = storage.RecordKeyDatabase( storage.TABLE_NAME_IMAGE_BLOBS, imageId )
    imageRecord = imageKey.get()
    if ( not imageRecord ) or ( not imageRecord.data ):  return '', 404  # Not found
    logging.warning(LogMessage( 'imageRecord.id=', imageRecord.id, 'imageRecord.mime=', imageRecord.mime ))

    httpResponse = flask.make_response( imageRecord.data )
    httpResponse.headers.set( 'Content-Type', imageRecord.mime )

    return httpResponse


