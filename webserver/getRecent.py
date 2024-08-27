# Retrieve summaries of recently-viewed surveys

# Import external modules
import json
import logging
import os
# Import app modules
from configuration import const as conf
import httpServer
from httpServer import app
import linkKey
import multi.survey
import storage
from text import LogMessage
import user



@app.get('/getRecent')
def recent( ):
    httpRequest, httpResponse = httpServer.requestAndResponse()

    # Collect inputs
    httpRequestId = os.environ.get( conf.REQUEST_LOG_ID )
    responseData = { 'success':False, 'httpRequestId':httpRequestId }
    cookieData = httpServer.validate( httpRequest, {}, responseData, httpResponse, crumbRequired=False, signatureRequired=False )
    if not cookieData.valid():  return httpResponse

    recentDestSummaries = []

    # Retrieve link-key records from cookie.
    recentLinkKeyToTime = user.retrieveRecentLinkKeys( httpRequest )
    if recentLinkKeyToTime:
        recentLinkKeyRecordKeys = [ storage.createKey(conf.LINK_KEY_CLASS_NAME, k) for k in recentLinkKeyToTime ]
        recentLinkKeyRecords = storage.get_multi( recentLinkKeyRecordKeys )

        destTypeXIdToLink = { (k.destinationType, str(k.destinationId)) : k.key.id()  for k in recentLinkKeyRecords if k }
        logging.warning(LogMessage( 'destTypeXIdToLink=', destTypeXIdToLink ))
        
        # Retrieve link-key destination records
        recentDestinationKeys = [ storage.createKey(k.destinationType, int(k.destinationId))  for k in recentLinkKeyRecords if k ]
        recentDestinationRecords = storage.get_multi( recentDestinationKeys )
        logging.warning(LogMessage( 'length recentDestinationRecords=', len(recentDestinationRecords) ))
        
        # Collect destination summaries.
        userId = cookieData.id()
        for r in recentDestinationRecords:
            logging.warning(LogMessage( 'recentDestinationRecord=', r ))
            if r is None:  continue
            destTypeAndId = ( r.key.kind(), str(r.key.id()) )
            logging.warning(LogMessage( 'destTypeAndId=', destTypeAndId ))
            
            linkKey = destTypeXIdToLink.get( destTypeAndId, None )
            logging.warning(LogMessage( 'linkKey=', linkKey ))

            if not linkKey:  continue
            recentDestSummary = { 'type':r.key.kind() }
            recentDestSummary['linkKey'] = linkKey
            recentDestSummary['time'] = recentLinkKeyToTime[ linkKey ]
            recentDestSummary['title'] = r.title  if r.title  else ''
            detail = r.detail
            recentDestSummary['detail'] = detail  if detail  else ''
            recentDestSummary['frozen'] = r.freezeUserInput
            recentDestSummary['mine'] = ( r.creator == userId )
            recentDestSummary['freezeNewProposals'] = hasattr( r, 'freezeNewProposals' ) and r.freezeNewProposals
            recentDestSummary['hideReasons'] = r.hideReasons  if hasattr( r, 'hideReasons' )  else False
            recentDestSummaries.append( recentDestSummary )

        logging.warning(LogMessage( 'recentDestSummaries=', recentDestSummaries ))
        
        # Order summaries by time.
        recentDestSummaries = sorted( [r for r in recentDestSummaries if r] , key=lambda r:r['time'] , reverse=True )

    logging.warning(LogMessage( 'recentDestSummaries=', recentDestSummaries ))
    
    responseData.update( { 'success':True, 'recents':recentDestSummaries } )
    return httpServer.outputJson( cookieData, responseData, httpResponse )


