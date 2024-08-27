# Shared functions for all http request service classes.

from configuration import const as conf
# Import external modules
import flask
if conf.IS_CLOUD:  import google.appengine.api
import json
import logging
import os
from werkzeug.routing import BaseConverter
# Import app modules
import common
import cookie
import linkKey
import time
import user



log = False

# Global variables are not reset for each request, because flask is a continuing process.


########################################################################
# HTTP-server configuration

def createFlaskApp( filename ):
    app = flask.Flask( filename, static_url_path='' )  # Use static_url_path to maintain the existing path to docs
    app.config['MAX_CONTENT_LENGTH'] = conf.MAX_IMAGE_BYTES  # File upload size limit
    if conf.IS_CLOUD:  app.wsgi_app = google.appengine.api.wrap_wsgi_app( app.wsgi_app )
    return app

app = createFlaskApp( __name__ )


# Page-routing parameter types 
class AlphaNumericUrlParamConverter( BaseConverter ):
    regex = r'[0-9A-Za-z]+'

app.url_map.converters['alphanumeric'] = AlphaNumericUrlParamConverter

class SliceKeyUrlParamConverter( BaseConverter ):
    regex = r'[0-9A-Za-z:\-]+'

app.url_map.converters['slicekey'] = SliceKeyUrlParamConverter

class ImageIdUrlParamConverter( BaseConverter ):
    regex = r'[0-9a-z\-]+'

app.url_map.converters['imageid'] = ImageIdUrlParamConverter



########################################################################
# Methods

class HttpRequest( object ):

    def __init__( self ):
        self.flaskRequest = flask.request

    def getUrlParams( self ):
        return self.flaskRequest.args

    def getUrlParam( self, name, defaultValue ):
        return self.flaskRequest.args.get( name, defaultValue )

    def postFormParams( self ):
        return self.flaskRequest.form

    def postJsonData( self ):
        return self.flaskRequest.get_json()   # Error 400 if accessed from a GET request

    @property
    def cookies( self ):
        return self.flaskRequest.cookies

    @property
    def headers( self ):
        return self.flaskRequest.headers


def requestAndResponse( ):
    return HttpRequest(), flask.make_response()



# Checks that title + detail length is greater than minimum
def isLengthOk( title, detail, lengthMin ):
    totalLength = 0
    totalLength += len(title) if title  else 0
    totalLength += len(detail) if detail  else 0;
    return ( totalLength >= lengthMin )

def isLengthTooShort( title, detail, minLength=30 ):
    totalLength = ( len(title)  if title  else 0 ) + ( len(detail)  if detail  else 0 )
    return ( totalLength < minLength )

# Checks that title + detail length is less than maximum
def isLengthTooLong( title, detail, maxLength=1000 ):
    totalLength = ( len(title)  if title  else 0 ) + ( len(detail)  if detail  else 0 )
    if conf.isDev and log:  logging.debug( 'isLengthTooLong() totalLength={} maxLength={}'.format(totalLength, maxLength) )
    return ( maxLength < totalLength )


# Returns CookieData
def validate( httpRequest, httpInput, responseData, httpResponse, 
        idRequired=True, loginRequired=False, crumbRequired=True, signatureRequired=True, makeValid=False, outputError=True ):

    if not idRequired:  crumbRequired = False;  signatureRequired=False;

    # Convert URL parameters to a map
    if conf.isDev and log:  logging.debug( 'type(httpInput)=' + str( type(httpInput) ) )
    if conf.isDev and log:  logging.debug( 'type(httpInput)__name__=' + str( type(httpInput).__name__ ) )
    if not isinstance( httpInput, dict ):
        # httpInput may be UnicodeMultiDict, or other custom mapping class from webapp2.RequestHandler.request.GET
        httpInput = {  i[0] : httpRequest.getUrlParams()[ i[0] ]  for i in httpRequest.getUrlParams().items()  }

    cookieData = user.validate( httpRequest, httpInput, crumbRequired=crumbRequired, signatureRequired=signatureRequired, 
        makeValid=makeValid )
    if conf.isDev and log:  logging.debug( 'validate() cookieData=' + str(cookieData) )
    
    # Output error
    if not cookieData:
        if idRequired and outputError:  outputJson( CookieData(), responseData, httpResponse, errorMessage='Null cookieData' )
        return CookieData()  # Always return CookieData that is non-null, but maybe invalid
    elif cookieData.errorMessage:
        if idRequired and outputError:  outputJson( cookieData, responseData, httpResponse, errorMessage=cookieData.errorMessage )
    elif not cookieData.browserId:
        if idRequired and outputError:  outputJson( cookieData, responseData, httpResponse, errorMessage='Null browserId' )
    elif not cookieData.loginId:
        if loginRequired:
            cookieData.errorMessage = conf.NO_LOGIN
            if outputError:  outputJson( cookieData, responseData, httpResponse, errorMessage=conf.NO_LOGIN )

    return cookieData


# Writes instantiated template to httpResponse
# Requires templateFilepath relative to this directory -- sub-directories must qualify path
def outputTemplate( templateFilepath, templateValues, httpResponse, cookieData=None, errorMessage=None ):
    logging.debug( 'httpServer.outputTemplate() templateFilepath=' + templateFilepath )

    if errorMessage:
        if conf.isDev:  logging.error( 'outputTemplate() errorMessage=' + errorMessage )
        templateValues['errorMessage'] = errorMessage

    if cookieData:
        # Signing modified cookies requires javascript-browser-fingerprint
        cookieData.sign()
        cookie.setCookieData( cookieData.data, cookieData.dataNew, getUseSecureCookie(), httpResponse )

    __setStandardHeaders( httpResponse )
    httpResponse.data = flask.render_template( templateFilepath, **templateValues )
    return httpResponse


# Modifies responseData and httpResponse
def outputJson( cookieData, responseData, httpResponse, errorMessage=None ):

    if errorMessage:
        if conf.isDev:  logging.error( 'outputJson() errorMessage=' + errorMessage )
        responseData['success'] = False
        responseData['message'] = errorMessage

    if cookieData:
        if cookieData.output:
            if conf.isDev:  logging.debug( 'outputJson() cookieData=' + str(cookieData) )
            raise Exception( 'outputJson() called more than once on cookieData=' + str(cookieData) )
        cookieData.output = True
        cookieData.sign()
        cookie.setCookieData( cookieData.data, cookieData.dataNew, getUseSecureCookie(), httpResponse )

    __setStandardHeaders( httpResponse )
    logging.warning( 'httpServer.outputJson() responseData=' + str(responseData) )
    httpResponse.data = json.dumps(responseData)
    return httpResponse


def __setStandardHeaders( httpResponse ):
    httpResponse.headers['X-Frame-Options'] = 'deny' 
    httpResponse.headers['Content-Security-Policy'] = "frame-ancestors 'none'"


def getUseSecureCookie( ):  return not conf.isDev


# Creates link-key, stores link-key in persistent record, and adds link-key to recent links in cookie.
def createAndStoreLinkKey( destClassName, destinationId, loginRequired, cookieData ):
    linkKeyRecord = linkKey.createAndStoreLinkKey( destClassName, destinationId, loginRequired )
    user.storeRecentLinkKey( linkKeyRecord.id, cookieData )

    return linkKeyRecord



########################################################################
# Filtering / transforming persistent record fields for display

def linkKeyToDisplay( linkKeyRecord ):
    return {
        'loginRequired': (linkKeyRecord.loginRequired == True) ,
        'id': linkKeyRecord.key.id()
    }

def requestToDisplay( requestRecord, userId ):
    display = {
        'id': str(requestRecord.key.id()),
        'timeCreated': requestRecord.timeCreated ,
        'title': requestRecord.title,
        'detail': requestRecord.detail,
        'mine': ( requestRecord.creator == userId ),
        'allowEdit': ( userId == requestRecord.creator ) and requestRecord.allowEdit ,
        'freezeUserInput': requestRecord.freezeUserInput ,
        'freezeNewProposals': requestRecord.freezeNewProposals ,
        'adminHistory': common.decodeChangeHistory( requestRecord.adminHistory ) ,
    }
    # Only set if used
    if requestRecord.hideReasons:  display['hideReasons'] = requestRecord.hideReasons
    if requestRecord.doneLink:  display['doneLink'] = requestRecord.doneLink
    return display

# Accepts requestRecord to copy top-level-attributes like freeze and hide-reasons
def proposalToDisplay( proposalRecord, userId, requestRecord=None ):
    mySurvey = (requestRecord.creator == userId)  if requestRecord  else  (proposalRecord.creator == userId)
    freezeUserInput = proposalRecord.freezeUserInput or (requestRecord and requestRecord.freezeUserInput)
    sendVoteCounts = mySurvey or freezeUserInput
    display = {
        'id': str(proposalRecord.key.id()),
        'timeCreated': proposalRecord.timeCreated ,
        'title': proposalRecord.title,
        'detail': proposalRecord.detail,
        'mine': (proposalRecord.creator == userId),
        'mySurvey': mySurvey ,
        'allowEdit': (userId == proposalRecord.creator) and proposalRecord.allowEdit ,
        'freezeUserInput': freezeUserInput ,
        'adminHistory': common.decodeChangeHistory( proposalRecord.adminHistory ) ,
    }
    # Only set if used
    if proposalRecord.emptyProId:  display['emptyProId'] = str(proposalRecord.emptyProId)
    if proposalRecord.emptyConId:  display['emptyConId'] = str(proposalRecord.emptyConId)
    if proposalRecord.hideReasons or (requestRecord and requestRecord.hideReasons):  display['hideReasons'] = True
    if sendVoteCounts:
        display['sendVoteCounts'] = True
        display['numPros'] = proposalRecord.numPros
        display['numCons'] = proposalRecord.numCons
    return display

def reasonToDisplay( reasonRecord, userId, proposal=None, request=None ):
    proposalRecord = proposal
    requestRecord = request
    mySurvey = (requestRecord.creator == userId)  if requestRecord  else  (proposalRecord.creator == userId)
    freezeUserInput = (requestRecord and requestRecord.freezeUserInput) or (proposalRecord and proposalRecord.freezeUserInput)
    sendVoteCounts = mySurvey or freezeUserInput
    display = {
        'proposalId': reasonRecord.proposalId,
        'id': str(reasonRecord.key.id()),
        'content': reasonRecord.content,
        'proOrCon': reasonRecord.proOrCon,
        'mine': (reasonRecord.creator == userId),
        'allowEdit': (userId == reasonRecord.creator) and reasonRecord.allowEdit,
        'score': reasonRecord.score
    }
    if sendVoteCounts:
        display['sendVoteCounts'] = True
        display['voteCount'] = reasonRecord.voteCount
    return display
