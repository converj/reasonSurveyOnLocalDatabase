# Data record classes

# Import external modules
import collections
import copy
import datetime
import hashlib
import json
import logging
import time
# Import app modules
from multi.configMulti import conf
import stats
import multi.shared
import multi.survey
import multi.userAnswers
import storage
import text
from text import LogMessage
import user


#####################################################################################################
# Data record classes

# Use cases:
#  Show results:  top answers by votes
#  Suggest answer:  top scored answers by start words
#  Suggest higher (or lower) answer:  top scored answers higher (lower) than current answer

# A piece of the VoteAggregate key, with meta-data
class SubKey( object ):
    def __init__( self, value, doAggregate=False, isId=False, isHash=False, isNumber=False, mergeWords=False, childDistribution=False ):
        self.value = value
        self.doAggregate = doAggregate
        self.isId = isId
        self.isHash = isHash
        self.isNumber = isNumber
        self.mergeWords = mergeWords  # For matching words in text-answer + reason, have to search by combined parent + last subkey words
        self.childDistribution = childDistribution

    def isText( self ):  return not ( self.isId or self.isHash or self.isNumber )

    def __repr__( self ):
        valueStr = '"{}"'.format( self.value )  if ( (self.value is not None) and self.isText() )  else str( self.value )
        flags = [
            ( 'doAggregate'  if self.doAggregate  else None ) ,
            ( 'isId'  if self.isId  else None ) ,
            ( 'isHash'  if self.isHash  else None ) ,
            ( 'isNumber'  if self.isNumber  else None ) ,
            ( 'mergeWords'  if self.mergeWords  else None ) ,
            ( 'childDistribution'  if self.childDistribution  else None ) ,
        ]
        flags = [ f  for f in flags  if f is not None ]
        return 'SubKey{' + ' '.join( [valueStr] + flags ) + '}'

    def __eq__( self, other ):
        return (
            isinstance( other, SubKey ) and
            ( self.value == other.value ) and
            ( self.doAggregate == other.doAggregate ) and
            ( self.isId == other.isId ) and
            ( self.doAggregate == other.doAggregate ) and
            ( self.isHash == other.isHash ) and
            ( self.isNumber == other.isNumber ) and
            ( self.mergeWords == other.mergeWords ) and
            ( self.childDistribution == other.childDistribution )
        )

    @staticmethod
    def subkeysToStrings( subkeys ):
        subkeyStrings = []
        for s in subkeys:
            if s.value is None: subkeyStrings.append( '' )
            elif s.isNumber:    subkeyStrings.append( str(s.value) )
            elif s.isHash:      subkeyStrings.append( s.value )
            elif s.isId:        subkeyStrings.append( s.value )
            else:               subkeyStrings.append( multi.shared.hashForKey(s.value) )
        return subkeyStrings



if conf.IS_CLOUD:

    # Vote-count aggregate, keyed by a series of SubKey
    # If reason or other answer parts are null, might need vote-counts for own/ancesstor results
    class VoteAggregate( ndb.Model ):

        surveyId = ndb.StringProperty()   # To verify answer belongs to survey

        parentKey = ndb.StringProperty()  # To find top answers for a given parent-question, or top reasons for a given parent-answer
        grandparentKey = ndb.StringProperty()  # To find top answers & reasons for a given grandparent-question
        greatgrandparentKey = ndb.StringProperty()  # To find top budget items & amounts & reasons for a great-grandparent question

        grandparentSubkeyText = ndb.StringProperty()  # To retrieve budget-item text for top budget-item-allocations
        parentSubkeyText = ndb.StringProperty()  # To retrieve top answers for a given grandparent-question
        lastSubkeyText = ndb.StringProperty()  # To find top non-null answers

        words = ndb.StringProperty( repeated=True )  # For matching input-words to make suggestions

        voteCount = ndb.IntegerProperty( default=0 )  # Votes for last-subkey, non-negative
        score = ndb.FloatProperty( default=0 )
        childToVotes = ndb.JsonProperty()
        
        @staticmethod
        def create( surveyId, subkeys ):
            record = VoteAggregate( id=VoteAggregate.toKeyId(surveyId, subkeys), surveyId=surveyId )
            record.parentKey = VoteAggregate.toKeyId( surveyId, subkeys[0 : -1] )
            record.grandparentKey = VoteAggregate.toKeyId( surveyId, subkeys[0 : -2] )
            record.greatgrandparentKey = VoteAggregate.toKeyId( surveyId, subkeys[0 : -3] )

            lastSubkey = subkeys[ -1 ]
            record.lastSubkeyText = str( lastSubkey.value )  if not text.isEmpty(lastSubkey.value)  else None
            record.parentSubkeyText = str( subkeys[-2].value )  if ( 2 <= len(subkeys) ) and not text.isEmpty(subkeys[-2].value)  else None
            record.grandparentSubkeyText = str( subkeys[-3].value )  if ( 3 <= len(subkeys) ) and not text.isEmpty(subkeys[-3].value)  else None

            # Interpret last-subkey: parse as number or index words
            if lastSubkey.isText():
                searchableText = ' '.join(  [ s.value or ''  for i,s in enumerate(subkeys)  if (i == len(subkeys)-1) or (s.mergeWords and s.isText()) ]  )
                words = multi.shared.tokenizeText( searchableText )
                words = words[ 0 : conf.MAX_WORDS_TO_INDEX ]  # Limit number of words indexed
                record.words = text.tuples( words, conf.MAX_COMPOUND_WORD_LENGTH )

            return record

        @staticmethod
        def retrieve( surveyId, subkeys ):
            return VoteAggregate.get_by_id( VoteAggregate.toKeyId(surveyId, subkeys) )

        @staticmethod
        def toKeyId( surveyId, subkeys ):
            subkeyStrings = SubKey.subkeysToStrings( subkeys )
            return '-'.join( [surveyId] + subkeyStrings )

        def incrementVoteCount( self, increment ):  self.setVoteCount( self.voteCount + increment )

        def setVoteCount( self, newVoteCount ):
            self.voteCount = max( 0, newVoteCount )
            self.score = multi.shared.scoreDiscountedByLength( self.voteCount, self.lastSubkeyText )

        def setChildVotes( self, child, votes ):
            if self.childToVotes is None:  self.childToVotes = {}
            self.childToVotes[ child ] = votes

        def medianChild( self ):  return stats.medianKey( self.childToVotes )
        def averageChild( self ):  return stats.averageKey( self.childToVotes )

        def lastSubkeyHash( self ):  return multi.shared.hashForKey( self.lastSubkeyText )




    #####################################################################################################
    # Methods for voting and incrementing vote-aggregates

    # Assumes that user is voting for answerContent & reason, which may be null
    # Allows only 1 answer & reason per subkey-path
    #  User could input a group of subkey-paths (example: budget items), but only 1 answer/reason per path
    #  Proposal-reasons are not subkey-paths, because proposal-reasons must exist even without votes
    # Use numUnaggregatedSubkeys to only change aggregate-votes for answer/UGC ancestors, not question ancestors
    # If any vote/aggregate increment fails... then undo all vote increments via transaction
    @staticmethod
    @ndb.transactional(xg=True, retries=conf.MAX_VOTE_RETRY)
    def vote( userId, surveyId, subkeys, answerContent, reason, numericAnswer=False, countUniqueVoters=False ):

        logging.debug(LogMessage('userId=', userId, 'surveyId=', surveyId, 'subkeys=', subkeys))

        # Store answer in user-survey-answers
        userVoteRecord, answerOld, questionHadAnswer = multi.userAnswers.updateAnswer( userId, surveyId, subkeys, answerContent, reason )
        logging.debug(LogMessage('userVoteRecord=', userVoteRecord))
        if not userVoteRecord:  return None, None, None, None

        # Prepare subkeys for incrementing vote-aggregates
        subkeysWithAnswerOld = subkeys + [
            SubKey(value=answerOld.content, isNumber=numericAnswer, doAggregate=True) ,
            SubKey(value=answerOld.reason, doAggregate=True)
        ]
        subkeysWithAnswerNew = subkeys + [
            SubKey(value=answerContent, isNumber=numericAnswer, doAggregate=True) ,
            SubKey(value=reason, doAggregate=True)
        ]
        logging.debug(LogMessage('subkeysWithAnswerNew=', subkeysWithAnswerNew))

        # Increment vote-aggregates
        oldAnswerIsNull = multi.userAnswers.answerIsEmpty( answerOld.content, answerOld.reason )
        newAnswerIsNull = multi.userAnswers.answerIsEmpty( answerContent, reason )
        aggregateRecordsNew, aggregateRecordsOld = incrementVoteAggregates( surveyId, subkeysWithAnswerOld, subkeysWithAnswerNew, oldAnswerIsNull, newAnswerIsNull )

        # Increment vote-aggregate for question unique voter count
        questionVotes = None
        if countUniqueVoters:
            questionVotes = VoteAggregate.retrieve( surveyId, subkeys[0:1] )
            if questionVotes and questionHadAnswer and newAnswerIsNull:
                questionVotes.incrementVoteCount( -1 )
                questionVotes.put()
            elif (not questionHadAnswer) and (not newAnswerIsNull):
                if not questionVotes:  questionVotes = VoteAggregate.create( surveyId, subkeys[0:1] )
                questionVotes.incrementVoteCount( 1 )
                questionVotes.put()
        logging.debug(LogMessage('questionVotes=', questionVotes))

        return userVoteRecord, aggregateRecordsNew, aggregateRecordsOld, questionVotes



    @staticmethod
    def voteRanking( userId, surveyId, questionId, optionId, rankNew, reasonNew, ranking=None, optionsAllowed=None ):

        logging.debug(LogMessage( 'userId=', userId, 'surveyId=', surveyId, 'questionId=', questionId, 'optionId=', optionId, 'rankNew=', rankNew, 'reasonNew=', reasonNew ))
        logging.debug(LogMessage( 'ranking=', ranking ))
        logging.debug(LogMessage( 'optionsAllowed=', optionsAllowed ))

        userVoteRecord, rankingOld, rankingNew = voteRankingChangeUserVoteCloud(
            userId, surveyId, questionId, optionId, rankNew, reasonNew, ranking=ranking, optionsAllowed=optionsAllowed )

        # For each option... incrementVoteAggregates() with its old & new rank
        for o in set( rankingOld.keys() ).union( set(rankingNew.keys()) ):
            logging.debug(LogMessage('o=', o))

            oldAnswer = rankingOld.get( o, {} )
            newAnswer = rankingNew.get( o, {} )

            oldContent = oldAnswer.get( multi.userAnswers.KEY_CONTENT, None )
            newContent = newAnswer.get( multi.userAnswers.KEY_CONTENT, None )
            
            oldReason = oldAnswer.get( multi.userAnswers.KEY_REASON, None )
            newReason = newAnswer.get( multi.userAnswers.KEY_REASON, None )

            logging.debug(LogMessage('oldAnswer=', oldAnswer, 'newAnswer=', newAnswer))

            if ( oldContent == newContent ) and ( oldReason == newReason ):  continue

            # Have to change each aggregate in a separate transaction to avoid "operating on too many entity groups in a single transaction"
            # Since all options are re-voted on each change, error recovery is quick,
            # so each aggregate-path can be changed in a separate transaction
            voteRankingChangeAggregate( surveyId, questionId, o,
                (int(newContent) if newContent else None), newReason,
                (int(oldContent) if oldContent else None), oldReason )

        return userVoteRecord

    @staticmethod
    @ndb.transactional(xg=True, retries=conf.MAX_VOTE_RETRY)
    def voteRankingChangeUserVoteCloud( userId, surveyId, questionId, optionId, rankNew, reasonNew, ranking=None, optionsAllowed=None ):
        return __voteRankingChangeUserVote( userId, surveyId, questionId, optionId, rankNew, reasonNew, ranking=None, optionsAllowed=optionsAllowed )

    @staticmethod
    @ndb.transactional(xg=True, retries=conf.MAX_VOTE_RETRY)
    def voteRankingChangeAggregate( surveyId, questionId, optionId, newRank, newReason, oldRank, oldReason ):
        if ( oldRank == newRank ) and ( oldReason == newReason ):  return

        # Prepare subkeys for incrementing vote-aggregates
        subkeysWithAnswerOld = [
            SubKey(value=questionId, isId=True) ,
            SubKey(value=optionId, isId=True, doAggregate=True, childDistribution=True) ,
            SubKey(value=oldRank, isNumber=True, doAggregate=True) ,
            SubKey(value=oldReason, doAggregate=True)
        ]
        logging.debug(LogMessage('subkeysWithAnswerOld=', subkeysWithAnswerOld))

        subkeysWithAnswerNew = [
            SubKey(value=questionId, isId=True) ,
            SubKey(value=optionId, isId=True, doAggregate=True, childDistribution=True) ,
            SubKey(value=newRank, isNumber=True, doAggregate=True) ,
            SubKey(value=newReason, doAggregate=True)
        ]
        logging.debug(LogMessage('subkeysWithAnswerNew=', subkeysWithAnswerNew))

        oldAnswerIsNull = multi.userAnswers.answerIsEmpty( oldRank, oldReason )
        newAnswerIsNull = multi.userAnswers.answerIsEmpty( newRank, newReason )
        aggregateRecordsNew, aggregateRecordsOld = incrementVoteAggregates(
            surveyId, subkeysWithAnswerOld, subkeysWithAnswerNew, oldAnswerIsNull, newAnswerIsNull )



    # For budget-question, which has to set 3 answer levels: content, amount, reason
    # Caller must specify the old content, so this function can remove or modify the old allocation
    @staticmethod
    @ndb.transactional(xg=True, retries=conf.MAX_VOTE_RETRY)
    def voteBudgetItem( userId, surveyId, questionId, itemOld, itemNew, amountNew, reasonNew ):

        logging.debug(LogMessage('userId=', userId, 'surveyId=', surveyId, 'questionId=', questionId, 'itemOld=', itemOld, 'itemNew=', itemNew, 'amountNew=', amountNew, 'reasonNew=', reasonNew))

        userVoteRecord = __storeAnswerBudgetItem( userId, surveyId, questionId, itemOld, itemNew, amountNew, reasonNew )

        # Prepare subkeys for incrementing vote-aggregates
        subkeysWithAnswerOld = [
            SubKey(value=questionId, isId=True) ,
            SubKey(value=itemOld, doAggregate=True, mergeWords=True, childDistribution=True) ,  # For vote-aggregates, item-subkey should be marked text, so that it is merged into search text for allocation-reason
            SubKey(value=answerOld.content, isNumber=True, doAggregate=True) ,
            SubKey(value=answerOld.reason, doAggregate=True)
        ]
        subkeysWithAnswerNew = [
            SubKey(value=questionId, isId=True) ,
            SubKey(value=itemNew, doAggregate=True, mergeWords=True, childDistribution=True) ,
            SubKey(value=amountNew, isNumber=True, doAggregate=True) ,
            SubKey(value=reasonNew, doAggregate=True)
        ]
        logging.debug(LogMessage('subkeysWithAnswerNew=', subkeysWithAnswerNew))

        oldAnswerIsNull = ( answerOld.content in [None, '', 0] ) and not answerOld.reason
        newAnswerIsNull = ( amountNew in [None, '', 0] ) and not reasonNew
        aggregateRecordsNew, aggregateRecordsOld = incrementVoteAggregates( surveyId, subkeysWithAnswerOld, subkeysWithAnswerNew, oldAnswerIsNull, newAnswerIsNull )
        return userVoteRecord, aggregateRecordsNew, aggregateRecordsOld



    # For list-question, caller must specify the old content, so this function can remove or modify the old answer
    @staticmethod
    @ndb.transactional(xg=True, retries=conf.MAX_VOTE_RETRY)
    def voteListItem( userId, surveyId, questionId, itemOld, itemNew, reasonNew, maxItems=5 ):

        logging.debug(LogMessage('userId=', userId, 'surveyId=', surveyId, 'questionId=', questionId, 'itemOld=', itemOld, 'itemNew=', itemNew, 'reasonNew=', reasonNew))

        userVoteRecord, errorMessage = __storeAnswerListItem( userId, surveyId, questionId, itemOld, itemNew, reasonNew, maxItems=maxItems )
        if errorMessage:  return None, None, None, errorMessage

        # Prepare subkeys for incrementing vote-aggregates
        subkeysWithAnswerOld = [
            SubKey(value=questionId, isId=True) ,
            SubKey(value=itemOld, doAggregate=True, mergeWords=True, childDistribution=True) ,  # For vote-aggregates, item-subkey should be marked text, so that it is merged into search text for reason
            SubKey(value=answerOld.reason, doAggregate=True)
        ]
        subkeysWithAnswerNew = [
            SubKey(value=questionId, isId=True) ,
            SubKey(value=itemNew, doAggregate=True, mergeWords=True, childDistribution=True) ,
            SubKey(value=reasonNew, doAggregate=True)
        ]
        logging.debug(LogMessage('subkeysWithAnswerNew=', subkeysWithAnswerNew))

        oldAnswerIsNull = multi.userAnswers.answerIsEmpty( itemOld, answerOld.reason )
        newAnswerIsNull = multi.userAnswers.answerIsEmpty( itemNew, reasonNew )
        aggregateRecordsNew, aggregateRecordsOld = incrementVoteAggregates( surveyId, subkeysWithAnswerOld, subkeysWithAnswerNew, oldAnswerIsNull, newAnswerIsNull )
        return userVoteRecord, aggregateRecordsNew, aggregateRecordsOld, None



    @staticmethod
    @ndb.transactional(xg=True, retries=conf.MAX_VOTE_RETRY)
    def voteSolutionReasonTransaction( userId, surveyId, questionId, problemId, solutionId, reasonId ):

        logging.debug(LogMessage('userId=', userId, 'surveyId=', surveyId, 'questionId=', questionId, 'problemId=', problemId, 'solutionId=', solutionId, 'reasonId=', reasonId))

        # Store answer in user-survey-answers
        if problemId:
            subkeys = [ SubKey(str(questionId), isId=True) , SubKey(str(problemId), isId=True) , SubKey(str(solutionId), isId=True) ]
        else:
            subkeys = [ SubKey(str(questionId), isId=True) , SubKey(str(solutionId), isId=True) ]
        userVoteRecord, answerOld, questionHadAnswer = multi.userAnswers.updateAnswer( userId, surveyId, subkeys, reasonId, None )
        if not userVoteRecord:  return None, None, None, None, None

        reasonIdOld = int( answerOld.content )  if ( answerOld and answerOld.content )  else None

        # Decrement reason losing vote
        reasonRecordOld = None
        if reasonIdOld is not None:
            reasonRecordOld = Content.retrieve( surveyId, questionId, [problemId, solutionId], contentId=reasonIdOld )
            logging.debug(LogMessage('reasonRecordOld=', reasonRecordOld))

            if reasonRecordOld and ( 1 <= reasonRecordOld.voteCount ):
                reasonRecordOld.incrementVoteCount( -1 )
                reasonRecordOld.put()

        # Increment reason gaining vote
        reasonRecordNew = None
        if reasonId is not None:
            reasonRecordNew = Content.retrieve( surveyId, questionId, [problemId, solutionId], contentId=reasonId )
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
            solutionRecord = Content.retrieve( surveyId, questionId, [problemId], contentId=solutionId )
            solutionRecord.incrementNumProsOrCons( proOrConOld, -1 )
            solutionRecord.incrementNumProsOrCons( proOrConNew, 1 )
            solutionRecord.put()
            # Change problem vote count
            if problemId:
                problemRecord = Content.retrieve( surveyId, questionId, [], contentId=problemId )
                problemRecord.incrementNumProsOrCons( proOrConOld, -1 )
                problemRecord.incrementNumProsOrCons( proOrConNew, 1 )
                problemRecord.put()

        return userVoteRecord, problemRecord, solutionRecord, reasonRecordNew, reasonRecordOld


    @staticmethod
    @ndb.transactional(xg=True, retries=conf.MAX_VOTE_RETRY)
    def voteProposalReason( userId, surveyId, subkeys, proposalId, reasonId ):

        logging.debug(LogMessage('userId=', userId, 'surveyId=', surveyId, 'subkeys=', subkeys))

        # Store answer in user-survey-answers
        userVoteRecord, answerOld, questionHadAnswer = multi.userAnswers.updateAnswer( userId, surveyId, subkeys, reasonId, None )
        if not userVoteRecord:  return None, None, None, None

        # Store proposal-reason vote-aggregates in reason-record
        #  Synchronizing votes from aggregate-record to reason-record is possible,
        #  but complex, and less inefficient for incrementing & querying top reasons
        # Similarly, store proposal pro/con vote-aggregates in proposal-record

        # Decrement old answer 
        reasonRecordOld = None
        if answerOld.content is not None:
            reasonIdOld = int( answerOld.content )
            reasonRecordOld = reason.Reason.get_by_id( reasonIdOld )
            logging.debug(LogMessage('reasonRecordOld=', reasonRecordOld))

            if reasonRecordOld and ( 1 <= reasonRecordOld.voteCount ):
                reasonRecordOld.incrementVoteCount( -1 )
                reasonRecordOld.put()

        # Increment new answer 
        reasonRecordNew = None
        if reasonId is not None:
            reasonRecordNew = reason.Reason.get_by_id( reasonId )
            logging.debug(LogMessage('reasonRecordNew=', reasonRecordNew))

            reasonRecordNew.incrementVoteCount( 1 )
            if ( userId != reasonRecordNew.creator ):  reasonRecordNew.allowEdit = False

            reasonRecordNew.put()

        # Count votes pro/con the proposal
        proposalRecord = proposal.Proposal.get_by_id( proposalId )
        if not proposalRecord:  proposalRecord = proposal.Proposal( id=proposalId )
        proOrConOld = None  if (reasonRecordOld is None)  else reasonRecordOld.proOrCon
        proOrConNew = None  if (reasonRecordNew is None)  else reasonRecordNew.proOrCon
        if proOrConOld != proOrConNew:
            # Increase pro/con count for new reason
            if proOrConNew == conf.PRO:
                proposalRecord.numPros += 1
            elif proOrConNew == conf.CON:
                proposalRecord.numCons += 1
            # Decrease pro/con count for old reason
            if proOrConOld == conf.PRO:
                if ( 0 < proposalRecord.numPros ):  proposalRecord.numPros -= 1
            elif proOrConOld == conf.CON:
                if ( 0 < proposalRecord.numCons ):  proposalRecord.numCons -= 1
            # Store
            proposalRecord.put()

        return userVoteRecord, proposalRecord, reasonRecordNew, reasonRecordOld



    @staticmethod
    def incrementVoteAggregates( surveyId, subkeysWithAnswerOld, subkeysWithAnswerNew, oldAnswerIsNull, newAnswerIsNull ):

        logging.debug(LogMessage('subkeysWithAnswerOld=', subkeysWithAnswerOld, 'subkeysWithAnswerNew=', subkeysWithAnswerNew, 'oldAnswerIsNull=', oldAnswerIsNull, 'newAnswerIsNull=', newAnswerIsNull))

        # Increment aggregates from least to most contended record, to minimize time that contended record is locked
        aggregateRecordsNew = []
        aggregateRecordsOld = []
        endSubkeyIndices = list(   reversed(  range( 1, len(subkeysWithAnswerNew)+1 )  )   )
        childVotesOld = 0
        childVotesNew = 0
        childOld = None
        childNew = None
        for endSubkeyIndex in endSubkeyIndices:
            subkeysForAggregateNew = subkeysWithAnswerNew[ 0 : endSubkeyIndex ]
            subkeysForAggregateOld = subkeysWithAnswerOld[ 0 : endSubkeyIndex ]
            logging.debug(LogMessage('endSubkeyIndex=', endSubkeyIndex, 'subkeysForAggregateNew=', subkeysForAggregateNew))
            if not subkeysForAggregateNew[ -1 ].doAggregate:  continue

            aggregateRecordNew, aggregateRecordOld = incrementVoteAggregate(
                surveyId, subkeysForAggregateOld, subkeysForAggregateNew, oldAnswerIsNull, newAnswerIsNull,
                childOld, childNew, childVotesOld, childVotesNew )

            aggregateRecordsNew.append( aggregateRecordNew )
            aggregateRecordsOld.append( aggregateRecordOld )

            childOld = aggregateRecordOld.lastSubkeyText  if aggregateRecordOld  else None
            childNew = aggregateRecordNew.lastSubkeyText  if aggregateRecordNew  else None
            childVotesOld = aggregateRecordOld.voteCount  if aggregateRecordOld  else 0
            childVotesNew = aggregateRecordNew.voteCount  if aggregateRecordNew  else 0
            logging.debug(LogMessage('childOld=', childOld, 'childVotesOld=', childVotesOld, 'childNew=', childNew, 'childVotesNew=', childVotesNew))

        return aggregateRecordsNew, aggregateRecordsOld

    # Increment aggregate vote count, inside a transaction
    # Returns updated aggregate-record, or throws transaction-conflict exception
    @staticmethod
    def incrementVoteAggregate( surveyId, subkeysForAggregateOld, subkeysForAggregateNew, oldAnswerIsNull, newAnswerIsNull,
        childOld, childNew, childVotesOld, childVotesNew ):
        logging.debug(LogMessage('surveyId=', surveyId, 'subkeysForAggregateOld=', subkeysForAggregateOld,
            'subkeysForAggregateNew=', subkeysForAggregateNew, 'oldAnswerIsNull=', oldAnswerIsNull, 'newAnswerIsNull=', newAnswerIsNull,
            'childOld=', childOld, 'childNew=', childNew, 'childVotesOld=', childVotesOld, 'childVotesNew=', childVotesNew))

        # Only change aggregate-votes when answer moved outside that ancestor?
        #  + More efficient
        #  Yes, if answer already exists inside ancestor, no need to increment (or if new-answer is null, and answer does not exist)
        #  No, answer cannot move outside ancestor -- even for budget, moving share to another slice requires multiple steps
        #  No, this leaves child-distribution stale
        sameSubkeys = ( subkeysForAggregateOld == subkeysForAggregateNew )
        sameAnswer = sameSubkeys and ( oldAnswerIsNull == newAnswerIsNull )
        storeDistribution = subkeysForAggregateNew[-1].childDistribution
        collectDistribution = subkeysForAggregateNew[-2].childDistribution
        logging.debug(LogMessage('sameSubkeys=', sameSubkeys, 'sameAnswer=', sameAnswer, 'storeDistribution=', storeDistribution, 'collectDistribution=', collectDistribution))
        if sameAnswer and (not storeDistribution) and (not collectDistribution):  return None, None

        # Decrement old answer
        # Cannot skip retrieve aggregateRecord when answerIsNull
        #  Causes the old child-distribution to be overwritten entirely, not incrementally
        #  Causes an error in voteCount for any ancestor
        aggregateRecordOld = None
        aggregateRecordOld = VoteAggregate.retrieve( surveyId, subkeysForAggregateOld )
        if aggregateRecordOld:
            if not oldAnswerIsNull:  aggregateRecordOld.incrementVoteCount( -1 )
            # Store decremented count
            if not sameSubkeys:
                if ( aggregateRecordOld.voteCount <= 0 ):  aggregateRecordOld.key.delete()
                else:  aggregateRecordOld.put()
            logging.debug(LogMessage('aggregateRecordOld=', aggregateRecordOld))

        # Increment new answer
        aggregateRecordNew = None
        aggregateRecordNew = aggregateRecordOld  if sameSubkeys  else VoteAggregate.retrieve( surveyId, subkeysForAggregateNew )
        if not aggregateRecordNew:  aggregateRecordNew = VoteAggregate.create( surveyId, subkeysForAggregateNew )
        logging.debug(LogMessage('aggregateRecordNew=', aggregateRecordNew))

        if not newAnswerIsNull:  aggregateRecordNew.incrementVoteCount( 1 )
        # Store incremented count
        if ( aggregateRecordNew.voteCount <= 0 ):
            aggregateRecordNew.voteCount = 0
            aggregateRecordNew.key.delete()
        else:
            if storeDistribution:
                if childOld is not None:  aggregateRecordNew.setChildVotes( childOld, childVotesOld )
                if childNew is not None:  aggregateRecordNew.setChildVotes( childNew, childVotesNew )
            aggregateRecordNew.put()
        logging.debug(LogMessage('aggregateRecordNew=', aggregateRecordNew))

        return aggregateRecordNew, aggregateRecordOld



    #####################################################################################################
    # Methods for retrieving vote-aggregates

    # For displaying results
    # For question, return all option-rating counts, as map{ optionId -> QuestionOption }
    @staticmethod
    def retrieveTopByVotes( surveyId, parentSubkeys, maxRecords=5, subkeyIsGrandparent=False, cursor=None ):
        parentKey = VoteAggregate.toKeyId( surveyId, parentSubkeys )
        aggRecords = None
        cursorNew = None
        hasMore = False
        if subkeyIsGrandparent:
            aggRecords, cursorNew, hasMore = VoteAggregate.query( VoteAggregate.surveyId==surveyId , VoteAggregate.grandparentKey==parentKey
                ).order( -VoteAggregate.voteCount ).fetch_page( maxRecords, start_cursor=cursor )
        else:
            aggRecords, cursorNew, hasMore = VoteAggregate.query( VoteAggregate.surveyId==surveyId , VoteAggregate.parentKey==parentKey
                ).order( -VoteAggregate.voteCount ).fetch_page( maxRecords, start_cursor=cursor )
        return aggRecords, cursorNew, hasMore


    # For suggesting higher/lower numeric answers & reasons while user inputs answer
    @staticmethod
    def retrieveTopNumericAnswersAndReasons( surveyId, grandparentSubkeys, answer=0, reasonStart=None, maxRecords=3 ):

        logging.debug(LogMessage('grandparentSubkeys=', grandparentSubkeys, 'answer=', answer, 'reasonStart=', reasonStart))

        grandparentKey = VoteAggregate.toKeyId( surveyId, grandparentSubkeys )
        logging.debug(LogMessage('grandparentKey=', grandparentKey))

        inputWords = multi.shared.tokenizeText( reasonStart )
        logging.debug(LogMessage('inputWords=', inputWords))

        records = []
        if inputWords and (0 < len(inputWords)):
            # Retrieve top-scored record matching last input-word
            #  "Sort property must be the same as the property to which the inequality filter is applied"
            #  So cannot sort by score and constrain above/below/not-equal current number-answer (rating / rank / slice-size),
            #  nor constrain to reason non-null
            #  Instead, just sample 3 top-scored answers, and keep at most 1 above & 1 below
            #  (Or query adjacent number values, one above and one below)
            # Results will be collected and match-scored in client
            records += VoteAggregate.query( 
                VoteAggregate.surveyId==surveyId, 
                VoteAggregate.grandparentKey==grandparentKey, 
                VoteAggregate.words==inputWords[-1],
                ).order( -VoteAggregate.score ).fetch( maxRecords )
        else:
            # Retrieve top-scored records
            records += VoteAggregate.query( 
                VoteAggregate.surveyId==surveyId, 
                VoteAggregate.grandparentKey==grandparentKey, 
                ).order( -VoteAggregate.score ).fetch( maxRecords )
        logging.debug(LogMessage('records=', records))

        # Filter out empty reasons
        records = [  r  for r in records  if r.lastSubkeyText and ( (r.parentSubkeyText != answer) or (r.lastSubkeyText != reasonStart) )  ]
        return records


    # For suggesting text answers & reasons while user inputs answer
    @staticmethod
    def retrieveTopAnswersAndReasons( surveyId, grandparentSubkeys, inputText=None, maxRecords=3 ):

        logging.debug(LogMessage('grandparentSubkeys=', grandparentSubkeys, 'inputText=', inputText))

        grandparentKey = VoteAggregate.toKeyId( surveyId, grandparentSubkeys )
        logging.debug(LogMessage('grandparentKey=', grandparentKey))

        inputWords = multi.shared.tokenizeText( inputText )
        logging.debug(LogMessage('inputWords=', inputWords))

        records = []
        if inputWords and (0 < len(inputWords)):
            # Retrieve top-voted record matching last input-word
            # Results will be collected and match-scored in client
            records += VoteAggregate.query(
                VoteAggregate.surveyId==surveyId,
                VoteAggregate.grandparentKey==grandparentKey,
                VoteAggregate.words==inputWords[-1],
                ).order( -VoteAggregate.score ).fetch( maxRecords )
        logging.debug(LogMessage('records=', records))

        # Filter out empty reasons
        records = [ r  for r in records  if r.lastSubkeyText ]
        return records



    # For suggesting budget allocations while user inputs answer
    @staticmethod
    def retrieveTopAllocationsAndReasons( surveyId, greatGrandparentSubkeys, inputText=None, maxRecords=3 ):
        greatgrandparentKey = VoteAggregate.toKeyId( surveyId, greatGrandparentSubkeys )
        logging.debug(LogMessage('greatgrandparentKey=', greatgrandparentKey))

        inputWords = multi.shared.tokenizeText( inputText )
        logging.debug(LogMessage('inputWords=', inputWords))

        records = []
        if inputWords and (0 < len(inputWords)):
            # Retrieve top-voted record matching last input-word
            # Results will be collected and match-scored in client
            records += VoteAggregate.query(
                VoteAggregate.surveyId==surveyId,
                VoteAggregate.greatgrandparentKey==greatgrandparentKey,
                VoteAggregate.words==inputWords[-1],
                ).order( -VoteAggregate.score ).fetch( maxRecords )
        logging.debug(LogMessage('records=', records))

        # Filter out empty reasons
        records = [ r  for r in records  if r.lastSubkeyText ]
        return records



    @staticmethod
    def logAllVoteAggregates( surveyId, parentSubkeys=None, grandparentSubkeys=None, maxRecords=1 ):

        logging.debug(LogMessage('logAllVoteAggregates()', 'parentSubkeys=', parentSubkeys, 'grandparentSubkeys=', grandparentSubkeys))

        parentKey = VoteAggregate.toKeyId( surveyId, parentSubkeys )  if parentSubkeys  else None
        logging.debug(LogMessage('logAllVoteAggregates()', 'parentKey=', parentKey))

        grandparentKey = VoteAggregate.toKeyId( surveyId, grandparentSubkeys )  if grandparentSubkeys  else None
        logging.debug(LogMessage('logAllVoteAggregates()', 'grandparentKey=', grandparentKey))

        allRecords = []
        if parentKey:
            allRecords = VoteAggregate.query( VoteAggregate.parentKey==parentKey ).fetch()
        elif grandparentKey:
            allRecords = VoteAggregate.query( VoteAggregate.grandparentKey==grandparentKey ).fetch()
        else:
            allRecords = VoteAggregate.query().fetch()

        for r in allRecords:
            logging.debug(LogMessage( 'r=', r ))



#################################################################################################
# Database

if not conf.IS_CLOUD:

    # Vote-aggregates for suggesting answers and for showing top answer results
    # Store individual user-answer-votes in a table and add group-by views to create aggregates
    #  + Better data integrity than realizing vote-aggregates
    #  + Easier voting logic than using select statements with group-by
    #  + Easier to manually inspect aggregates
    # Use single vote table with fields answerString & answerNumber, vs separate tables for rating, rank, checkmark, text, list, allocation...
    #  + Requires fewer tables and vote-aggregation views
    #  - A little confusing about what answer pieces are represented by answerString & answerNumber

    # Retrieving answer-text from user-vote-table, versus separate table with map{ hash -> text }
    #  - Storing reason-text in user-vote-table would create a lot of duplicate text that may be much longer than a hash
    #  + Storing reason-text in separate table may risk data out of sync, may require cleanup, and slows transactions
    #  + Don't optimize storage space first thing, optimize correctness and simplicity
    TABLE_NAME_VOTE = 'user_answer_vote'
    storage.databaseInitialize( f"""
        create table if not exists {TABLE_NAME_VOTE} (
         userId  varchar({user.const.ID_COOKIE_LENGTH})  not null ,
         surveyId  int  not null ,
         questionId  varchar(4)  not null ,
         optionId  varchar(4)  not null ,
         answerNumber  int  not null ,
         answerString  varchar({conf.maxLengthReason})  not null ,
         answerStringHash  char(32)  not null ,
         answerStringLength  float  as (  cast( length(answerString) as decimal )  )  not null ,
         answerStringWords  json  not null  default('[]') ,

         reason  varchar({conf.maxLengthReason})  not null ,
         reasonHash  char(32)  not null ,
         reasonLength  float  as (  cast( length(reason) as decimal )  )  not null ,
         reasonWords  json  not null  default('[]') ,

         foreign key (surveyId) references {multi.survey.TABLE_NAME}(id) ,
         primary key (userId, surveyId, questionId, optionId, answerNumber, answerStringHash, reasonHash) ,
         key (  ( cast(answerStringWords as char(100) array) )  ) ,
         key (  ( cast(reasonWords as char(100) array) )  )
        )
    """ )
    # Cannot use auto-generated answerStringHash in primary key.  "generated column as primary key is not supported"
    #  Generate hash in caller instead
    #  answerStringHash  char(32) generated always as (MD5(answerString))

    # Include answerStringWords and reasonWords in group-by and selected-fields, versus join against user-vote-table
    #  - Group-by comparison may be slow
    #  Could group-by unique fields only, and use max() on other pass-through fields, but it appears to be the same number of comparisons
    TABLE_NAME_VOTE_AGG_PER_REASON = 'vote_agg_per_reason'
    if not storage.viewExists( TABLE_NAME_VOTE_AGG_PER_REASON ):
        storage.databaseInitialize( f"""
            create view {TABLE_NAME_VOTE_AGG_PER_REASON} as select
             surveyId, questionId, optionId, answerNumber, answerString, answerStringHash, answerStringWords, reason, reasonHash, reasonWords,
             count(*) as voteCount,
             count(distinct(userId)) as voterCount,
             cast(count(*) as decimal) / greatest( 1.0, reasonLength/{float(conf.CHAR_LENGTH_UNIT)} ) as score
             from {TABLE_NAME_VOTE} group by surveyId, questionId, optionId, answerNumber, answerString, answerStringHash, answerStringWords, reason, reasonHash, reasonLength, reasonWords
        """ )

    TABLE_NAME_VOTE_AGG_PER_ANSWER_NUMBER = 'vote_agg_per_answer_num'
    if not storage.viewExists( TABLE_NAME_VOTE_AGG_PER_ANSWER_NUMBER ):
        storage.databaseInitialize( f"""
            create view {TABLE_NAME_VOTE_AGG_PER_ANSWER_NUMBER} as select
             surveyId, questionId, optionId, answerString, answerStringHash, answerNumber,
             count(*) as voteCount,
             count(distinct(userId)) as voterCount
             from {TABLE_NAME_VOTE} group by surveyId, questionId, optionId, answerString, answerStringHash, answerNumber
        """ )

    TABLE_NAME_VOTE_AGG_PER_ANSWER_STRING = 'vote_agg_per_answer_str'
    if not storage.viewExists( TABLE_NAME_VOTE_AGG_PER_ANSWER_STRING ):
        storage.databaseInitialize( f"""
            create view {TABLE_NAME_VOTE_AGG_PER_ANSWER_STRING} as select
             surveyId, questionId, optionId, answerString, answerStringHash, answerStringWords,
             count(*) as voteCount,
             count(distinct(userId)) as voterCount,
             cast(count(*) as decimal) / greatest( 1.0,  answerStringLength/{float(conf.CHAR_LENGTH_UNIT)} ) as score
             from {TABLE_NAME_VOTE} group by surveyId, questionId, optionId, answerString, answerStringHash, answerStringLength, answerStringWords
        """ )

    TABLE_NAME_VOTE_AGG_PER_OPTION = 'vote_agg_per_option'
    if not storage.viewExists( TABLE_NAME_VOTE_AGG_PER_OPTION ):
        storage.databaseInitialize( f"""
            create view {TABLE_NAME_VOTE_AGG_PER_OPTION} as select
             surveyId, questionId, optionId,
             count(*) as voteCount,
             count(distinct(userId)) as voterCount
             from {TABLE_NAME_VOTE} group by surveyId, questionId, optionId
        """ )

    TABLE_NAME_VOTE_AGG_PER_QUESTION = 'vote_agg_per_question'
    if not storage.viewExists( TABLE_NAME_VOTE_AGG_PER_QUESTION ):
        storage.databaseInitialize( f"""
            create view {TABLE_NAME_VOTE_AGG_PER_QUESTION} as select
             surveyId, questionId,
             count(*) as voteCount,
             count(distinct(userId)) as voterCount
             from {TABLE_NAME_VOTE} group by surveyId, questionId
        """ )


    # Assumes that user is voting for answerContent & reason, which may be null
    #  Applies to rating, checklist, and text questions
    # If any vote/aggregate increment fails... then leave partially completed
    def voteDatabase( userId, surveyId, questionId, optionId, answerNumber=0, answerString='', reason='' ):

        subkeys = [ SubKey(value=questionId, isId=True) ]
        if optionId:  subkeys.append( SubKey(value=optionId, isId=True) )
        logging.debug(LogMessage('userId=', userId, 'surveyId=', surveyId, 'subkeys=', subkeys))
        answerContent = answerString or answerNumber

        # Store answer in user-survey-answers
        userVoteRecord, answerOld, questionHadAnswer = multi.userAnswers.updateAnswer( userId, surveyId, subkeys, answerContent, reason )
        logging.debug(LogMessage('userVoteRecord=', userVoteRecord))
        if not userVoteRecord:  return None, None, None

        # Increment vote-aggregates
        answerStringHash = toHash( answerString )
        reasonHash = toHash( reason )
        __deleteVote( userId, surveyId, questionId, optionId, answerNumber, answerStringHash, reasonHash )
        __insertVote( userId, surveyId, questionId, optionId, answerNumber, answerString, answerStringHash, reason, reasonHash )

        aggregateRecordsNew, questionVotes = __retrieveVoteAggregatesDatabase( surveyId, questionId, optionId, answerNumber, answerStringHash, reasonHash )
        return userVoteRecord, aggregateRecordsNew, questionVotes

    def __insertVote( userId, surveyId, questionId, optionId, answerNumber, answerString, answerStringHash, reason, reasonHash ):
        if answerNumber is None:  return   # No need to count empty rating answer with reason only
        answerStringWords = json.dumps( multi.shared.textToTuples(answerString) )
        reasonWords = json.dumps( multi.shared.textToTuples(reason) )
        storage.databaseExecute( f"""
            insert into {TABLE_NAME_VOTE} (
             userId, surveyId, questionId, optionId, answerNumber, answerString, answerStringHash, answerStringWords, reason, reasonHash, reasonWords)
             values (
                %s,     %s,        %s,         %s,       %s,              %s,            %s,            %s,             %s,       %s,         %s     )
            """ ,
            parameters=(
             userId, surveyId, questionId, optionId, answerNumber, answerString, answerStringHash, answerStringWords, reason, reasonHash, reasonWords )
        )

    def __deleteVote( userId, surveyId, questionId, optionId, answerNumber, answerStringHash, reasonHash ):
        storage.databaseExecute( f"""
            delete from {TABLE_NAME_VOTE} where 
             userId=%s and surveyId=%s and questionId=%s and optionId=%s
            """ ,
            parameters=( userId, surveyId, questionId, optionId )
        )


    def voteRankingDatabase( userId, surveyId, questionId, optionId, rankNew, reasonNew, ranking=None, optionsAllowed=None ):

        logging.debug(LogMessage( 'userId=', userId, 'surveyId=', surveyId, 'questionId=', questionId, 'optionId=', optionId, 'rankNew=', rankNew, 'reasonNew=', reasonNew ))
        logging.debug(LogMessage( 'ranking=', ranking ))
        logging.debug(LogMessage( 'optionsAllowed=', optionsAllowed ))

        userVoteRecord, rankingOld, rankingNew = __voteRankingChangeUserVote(
            userId, surveyId, questionId, optionId, rankNew, reasonNew, ranking=ranking, optionsAllowed=optionsAllowed )

        # Remove all old rankings, since changing 1 ranking changes many others
        storage.databaseExecute(
            f" delete from {TABLE_NAME_VOTE} where userId=%s and surveyId=%s and questionId=%s " ,
            parameters=(userId, surveyId, questionId) )
        # Insert all new rankings
        for optionId in rankingNew:
            optionAnswer = rankingNew.get( optionId, {} )
            optionContent = optionAnswer.get( multi.userAnswers.KEY_CONTENT, '' ) or ''
            optionReason = optionAnswer.get( multi.userAnswers.KEY_REASON, '' ) or ''
            if not multi.userAnswers.answerIsEmpty( optionContent, optionReason ):
                answerNumber = optionContent
                answerString = ''
                __insertVote( userId, surveyId, questionId, optionId, answerNumber, answerString, toHash(answerString), optionReason, toHash(optionReason) )

        return userVoteRecord


    def voteBudgetItemDatabase( userId, surveyId, questionId, itemOld, itemNew, amountNew, reasonNew ):

        logging.debug(LogMessage('userId=', userId, 'surveyId=', surveyId, 'questionId=', questionId, 'itemOld=', itemOld, 'itemNew=', itemNew, 'amountNew=', amountNew, 'reasonNew=', reasonNew))

        userVoteRecord = __storeAnswerBudgetItem( userId, surveyId, questionId, itemOld, itemNew, amountNew, reasonNew )

        # Remove old item and its amount and reason
        if itemOld:
            storage.databaseExecute(
                f" delete from {TABLE_NAME_VOTE} where userId=%s and surveyId=%s and questionId=%s and answerStringHash=%s ",
                parameters=( userId, surveyId, questionId, toHash(itemOld) )
            )
        # Update votes and aggregates
        answerStringHash = toHash( itemNew )
        reasonHash = toHash( reasonNew )
        optionId = ''
        answerNumber = amountNew
        if itemNew and ( amountNew not in [None, '', 0] ):
            __insertVote( userId, surveyId, questionId, optionId, answerNumber, itemNew, answerStringHash, reasonNew, reasonHash )

        itemVoteRecord = __retrieveVotesForAnswerStr( surveyId, questionId, optionId, answerStringHash )
        amountVoteRecord = __retrieveVotesForAnswerNum( surveyId, questionId, optionId, answerStringHash, answerNumber )
        reasonVoteRecord = __retrieveVotesForReason( surveyId, questionId, optionId, answerNumber, answerStringHash, reasonHash )

        return userVoteRecord, itemVoteRecord, amountVoteRecord, reasonVoteRecord


    def voteListItemDatabase( userId, surveyId, questionId, itemOld, itemNew, reasonNew, maxItems=5 ):

        logging.debug(LogMessage('userId=', userId, 'surveyId=', surveyId, 'questionId=', questionId, 'itemOld=', itemOld, 'itemNew=', itemNew, 'reasonNew=', reasonNew))

        userVoteRecord, errorMessage = __storeAnswerListItem( userId, surveyId, questionId, itemOld, itemNew, reasonNew, maxItems=maxItems )
        if errorMessage:  return None, None, errorMessage

        # Remove old item and its reason
        if itemOld:
            storage.databaseExecute(
                f" delete from {TABLE_NAME_VOTE} where userId=%s and surveyId=%s and questionId=%s and answerStringHash=%s ",
                parameters=( userId, surveyId, questionId, toHash(itemOld) )
            )
        # Update votes and aggregates
        answerStringHash = toHash( itemNew )
        reasonHash = toHash( reasonNew )
        optionId = ''
        answerNumber = 0
        if itemNew:
            __insertVote( userId, surveyId, questionId, optionId, answerNumber, itemNew, answerStringHash, reasonNew, reasonHash )

        aggregateRecordsNew, questionVotes = __retrieveVoteAggregatesDatabase( surveyId, questionId, optionId, answerNumber, answerStringHash, reasonHash )
        return userVoteRecord, aggregateRecordsNew, None  # Null error-message



    def toHash( textValue ):
        if not textValue:  return ''  # Do not output null.  Make null and empty-string hash to the same ID.
        hasher = hashlib.md5()
        hasher.update( text.utf8(textValue) )
        return hasher.hexdigest()


    def __retrieveVoteAggregatesDatabase( surveyId, questionId, optionId, answerNumber, answerStringHash, reasonHash ):
        # Retrieve updated aggregates
        aggregateRecordsNew = [
            __retrieveVotesForReason(surveyId, questionId, optionId, answerNumber, answerStringHash, reasonHash) ,
            __retrieveVotesForAnswerNum(surveyId, questionId, optionId, answerStringHash, answerNumber) ,
            __retrieveVotesForAnswerStr(surveyId, questionId, optionId, answerStringHash) ,
            __retrieveVotesForOption(surveyId, questionId, optionId) ,
        ]

        questionVotes = __retrieveVotesForQuestion( surveyId, questionId )

        return aggregateRecordsNew, questionVotes

    def __retrieveVotesForReason( surveyId, questionId, optionId, answerNumber, answerStringHash, reasonHash ):
        return storage.RecordDatabase.fetchone(
            f" select * from {TABLE_NAME_VOTE_AGG_PER_REASON} where surveyId=%s and questionId=%s and optionId=%s and answerNumber=%s and answerStringHash=%s and reasonHash=%s " ,
            parameters=(surveyId, questionId, optionId, answerNumber, answerStringHash, reasonHash)
        )

    def __retrieveVotesForAnswerNum( surveyId, questionId, optionId, answerStringHash, answerNumber ):
        return storage.RecordDatabase.fetchone(
            f" select * from {TABLE_NAME_VOTE_AGG_PER_ANSWER_NUMBER} where surveyId=%s and questionId=%s and optionId=%s and answerStringHash=%s and answerNumber=%s " ,
            parameters=(surveyId, questionId, optionId, answerStringHash, answerNumber)
        )

    def __retrieveVotesForAnswerStr( surveyId, questionId, optionId, answerStringHash ):
        return storage.RecordDatabase.fetchone(
            f" select * from {TABLE_NAME_VOTE_AGG_PER_ANSWER_STRING} where surveyId=%s and questionId=%s and optionId=%s and answerStringHash=%s " ,
            parameters=(surveyId, questionId, optionId, answerStringHash)
        )

    def __retrieveVotesForOption( surveyId, questionId, optionId ):
        return storage.RecordDatabase.fetchone(
            f" select * from {TABLE_NAME_VOTE_AGG_PER_OPTION} where surveyId=%s and questionId=%s and optionId=%s " ,
            parameters=(surveyId, questionId, optionId)
        )

    def __retrieveVotesForQuestion( surveyId, questionId ):
        return storage.RecordDatabase.fetchone(
            f" select * from {TABLE_NAME_VOTE_AGG_PER_QUESTION} where surveyId=%s and questionId=%s " ,
            parameters=(surveyId, questionId)
        )


    # For displaying results
    def retrieveTopAnswersStrByVotesDatabase( surveyId, questionId, optionId, maxRecords=5, cursor=0 ):
        cursor = cursor or 0
        aggRecords = storage.RecordDatabase.fetchall( f"""
            select * from {TABLE_NAME_VOTE_AGG_PER_ANSWER_STRING} where surveyId=%s and questionId=%s and optionId=%s
             order by score desc  limit %s offset %s
            """ ,
            parameters=(surveyId, questionId, optionId, maxRecords, cursor) ,
            table=TABLE_NAME_VOTE_AGG_PER_ANSWER_STRING
        )
        logging.warning(LogMessage( 'aggRecords=', aggRecords ))
        more = ( 0 < len(aggRecords) )
        cursorNext = cursor + maxRecords  if more  else None
        return aggRecords, cursorNext, more

    def retrieveTopReasonsByVotesDatabase( surveyId, questionId, optionId, answerString, answerNumber, maxRecords=5, cursor=0 ):
        cursor = cursor or 0
        aggRecords = storage.RecordDatabase.fetchall( f"""
            select * from {TABLE_NAME_VOTE_AGG_PER_REASON}
             where surveyId=%s and questionId=%s and optionId=%s and answerStringHash=%s and answerNumber=%s
             order by score desc  limit %s offset %s
            """ ,
            parameters=(surveyId, questionId, optionId, toHash(answerString), answerNumber, maxRecords, cursor) ,
            table=TABLE_NAME_VOTE_AGG_PER_REASON
        )
        logging.warning(LogMessage( 'aggRecords=', aggRecords ))
        more = ( 0 < len(aggRecords) )
        cursorNext = cursor + maxRecords  if more  else None
        return aggRecords, cursorNext, more

    def retrieveTopReasonsForAnswerIdByVotesDatabase( surveyId, questionId, answerStringHash, maxRecords=5, cursor=0 ):
        cursor = cursor or 0
        aggRecords = storage.RecordDatabase.fetchall( f"""
            select * from {TABLE_NAME_VOTE_AGG_PER_REASON} where surveyId=%s and questionId=%s and answerStringHash=%s
             order by score desc  limit %s offset %s
            """ ,
            parameters=(surveyId, questionId, answerStringHash, maxRecords, cursor) ,
            table=TABLE_NAME_VOTE_AGG_PER_REASON
        )
        logging.warning(LogMessage( 'aggRecords=', aggRecords ))
        more = ( 0 < len(aggRecords) )
        cursorNext = cursor + maxRecords  if more  else None
        return aggRecords, cursorNext, more



    def suggestNumericAnswersAndReasonsFromDatabase( surveyId, questionId, optionId, answerString='', answerNumber=0, reasonStart=None, maxRecords=3 ):

        inputWords = multi.shared.tokenizeText( reasonStart )
        logging.debug(LogMessage('inputWords=', inputWords))

        records = []
        if inputWords and (0 < len(inputWords)):
            lastWords = [ inputWords[-1] ]
            if ( 2 <= len(inputWords) ):  lastWords.append( ' '.join(inputWords[-2:]) )
            # Retrieve top-scored record matching last input-word
            # Results will be collected and match-scored in client
            records = storage.RecordDatabase.fetchall( f"""
                select * from {TABLE_NAME_VOTE_AGG_PER_REASON}
                 where json_overlaps(reasonWords, %s) and surveyId=%s and questionId=%s and optionId=%s and answerString=%s
                 order by score desc  limit %s
                """ ,
                parameters=( json.dumps(lastWords), surveyId, questionId, optionId, answerString, maxRecords )
            )
        else:
            answerStringHash = toHash( answerString )
            records = storage.RecordDatabase.fetchall( f"""
                select * from {TABLE_NAME_VOTE_AGG_PER_REASON} where surveyId=%s and questionId=%s and optionId=%s and answerStringHash=%s
                 order by score desc  limit %s
                """ ,
                parameters=(surveyId, questionId, optionId, answerStringHash, maxRecords) ,
                table=TABLE_NAME_VOTE_AGG_PER_REASON
            )

        logging.warning(LogMessage('records=', records))

        # Filter out empty or redundant reasons
        records = [  r  for r in records  if r.reason and ( (r.answerNumber != answerNumber) or (r.reason != reasonStart) )  ]
        logging.warning(LogMessage('records=', records))

        return records


    def suggestAnswersAndReasonsFromDatabase( surveyId, questionId, inputText='', maxRecords=3 ):

        logging.warning(LogMessage( 'surveyId=', surveyId, 'questionId=', questionId, 'inputText=', inputText ))

        inputWords = multi.shared.tokenizeText( inputText )
        logging.debug(LogMessage('inputWords=', inputWords))

        records = []
        if inputWords and (0 < len(inputWords)):
            lastWords = [ inputWords[-1] ]
            if ( 2 <= len(inputWords) ):  lastWords.append( ' '.join(inputWords[-2:]) )

            # Retrieve top-scored record matching last input-word
            # Results will be collected and match-scored in client
            records = storage.RecordDatabase.fetchall( f"""
                select * from {TABLE_NAME_VOTE_AGG_PER_REASON}
                 where ( json_overlaps(answerStringWords, %s) or json_overlaps(reasonWords, %s) )
                  and surveyId=%s and questionId=%s
                 order by score desc  limit %s
                """ ,
                parameters=( json.dumps(lastWords), json.dumps(lastWords), surveyId, questionId, maxRecords )
            )

        else:
            records = storage.RecordDatabase.fetchall( f"""
                select * from {TABLE_NAME_VOTE_AGG_PER_REASON} where surveyId=%s and questionId=%s
                  order by score desc  limit %s
                """ ,
                parameters=(surveyId, questionId, maxRecords) ,
                table=TABLE_NAME_VOTE_AGG_PER_REASON
            )

        logging.debug(LogMessage('records=', records))

        # Filter out empty reasons
        records = [ r  for r in records  if r.reason ]
        return records


    def suggestAllocationsAndReasonsFromDatabase( surveyId, questionId, inputText='', maxRecords=3 ):

        logging.warning(LogMessage( 'surveyId=', surveyId, 'questionId=', questionId, 'inputText=', inputText ))

        inputWords = multi.shared.tokenizeText( inputText )
        logging.debug(LogMessage('inputWords=', inputWords))

        records = []
        if inputWords and (0 < len(inputWords)):
            lastWords = [ inputWords[-1] ]
            if ( 2 <= len(inputWords) ):  lastWords.append( ' '.join(inputWords[-2:]) )

            # Retrieve top-scored record matching last input-word
            # Results will be collected and match-scored in client
            records = storage.RecordDatabase.fetchall( f"""
                select * from {TABLE_NAME_VOTE_AGG_PER_REASON}
                 where ( json_overlaps(answerStringWords, %s) or json_overlaps(reasonWords, %s) )
                  and surveyId=%s and questionId=%s
                 order by score desc  limit %s
                """ ,
                parameters=( json.dumps(lastWords), json.dumps(lastWords), surveyId, questionId, maxRecords )
            )

        else:
            answerStringHash = toHash( answerString )
            records = storage.RecordDatabase.fetchall( f"""
                select * from {TABLE_NAME_VOTE_AGG_PER_REASON} where surveyId=%s and questionId=%s
                  order by score desc  limit %s
                """ ,
                parameters=(surveyId, questionId, maxRecords) ,
                table=TABLE_NAME_VOTE_AGG_PER_REASON
            )

        logging.debug(LogMessage('records=', records))

        # Filter out empty reasons
        records = [ r  for r in records  if r.reason ]
        return records




###############################################################################################
# Uniform interface

def voteRating( userId, surveyId, questionId, optionId, newRating, reason ):
    if conf.IS_CLOUD:
        subkeys = [ SubKey(questionId, isId=True) , SubKey(optionId, isId=True, doAggregate=True, childDistribution=True) ]
        userVotes, aggregateRecordsNew, aggregateRecordsOld, questionVotes = VoteAggregate.vote(
            userId, surveyId, subkeys, newRating, reason, numericAnswer=True )
        logging.debug(LogMessage( 'aggregateRecordsNew=', aggregateRecordsNew ))
        questionVotesInterim, optionVotes, reasonVotes = aggregateRecordsNew

    else:  # Database
        userVotes, aggregateRecordsNew, questionVotes = voteDatabase(
            userId, surveyId, questionId, optionId, answerNumber=newRating, reason=reason )
        logging.debug(LogMessage( 'aggregateRecordsNew=', aggregateRecordsNew ))
        reasonVotes, answerNumVotes, answerStrVotes, optionVotes = aggregateRecordsNew  if aggregateRecordsNew  else ( None, None, None, None )

    return userVotes, optionVotes, reasonVotes, questionVotes


def voteRanking( userId, surveyId, questionId, optionId, rankNew, reasonNew, ranking=None, optionsAllowed=None ):
    if conf.IS_CLOUD:
        return VoteAggregate.voteRanking( userId, surveyId, questionId, optionId, rankNew, reasonNew, ranking=ranking, optionsAllowed=optionsAllowed )
    else:  # Database
        return voteRankingDatabase( userId, surveyId, questionId, optionId, rankNew, reasonNew, ranking=ranking, optionsAllowed=optionsAllowed )

# TO DO:  Move userAnswers editing logic to userAnswers.py
def __voteRankingChangeUserVote( userId, surveyId, questionId, optionId, rankNew, reasonNew, ranking=None, optionsAllowed=None ):
    # Store answer in user-survey-answers
    userVoteRecord = multi.userAnswers.retrieveOrCreate( surveyId, userId )
    logging.debug(LogMessage('userVoteRecord=', userVoteRecord))

    # Update user answers, maintaining a valid ranking
    rankingOld = multi.userAnswers.getQuestionAnswers( userVoteRecord, questionId )  or  {}
    rankingOld = copy.deepcopy( rankingOld )
    logging.debug(LogMessage('rankingOld=', rankingOld))

    multi.userAnswers.setRanking( userVoteRecord, questionId, optionsAllowed, ranking, optionId, rankNew, reasonNew )
    rankingNew = multi.userAnswers.getQuestionAnswers( userVoteRecord, questionId )

    logging.debug(LogMessage('rankingOld=', rankingOld))
    logging.debug(LogMessage('rankingNew=', rankingNew))
    userVoteRecord.put()
    
    return userVoteRecord, rankingOld, rankingNew


def voteChecklist( userId, surveyId, questionId, optionId, newCheckmark, reason ):
    if conf.IS_CLOUD:
        subkeys = [ SubKey(questionId, isId=True) , SubKey(optionId, isId=True, doAggregate=True, childDistribution=True) ]
        userVotes, aggregateRecordsNew, aggregateRecordsOld, questionVotes = VoteAggregate.vote(
            userId, surveyId, subkeys, newCheckmark, reason, numericAnswer=True, countUniqueVoters=True )
        logging.debug(LogMessage( 'aggregateRecordsNew=', aggregateRecordsNew ))
        questionVotesInterim, optionVotes, reasonVotes = aggregateRecordsNew

    else:  # Database
        userVotes, aggregateRecordsNew, questionVotes = voteDatabase(
            userId, surveyId, questionId, optionId, answerNumber=newCheckmark, reason=reason )
        logging.debug(LogMessage( 'aggregateRecordsNew=', aggregateRecordsNew ))
        reasonVotes, answerNumVotes, answerStrVotes, optionVotes = aggregateRecordsNew or (None, None, None, None)

    return userVotes, optionVotes, reasonVotes, questionVotes

def voteText( userId, surveyId, questionId, answerString, reason ):
    if conf.IS_CLOUD:
        subkeys = [ SubKey(questionId, isId=True) ] 
        userVotes, aggregateRecordsNew, aggregateRecordsOld, questionVotes = VoteAggregate.vote( 
            userId, surveyId, subkeys, answerString, reason, numericAnswer=False )
        logging.debug(LogMessage( 'aggregateRecordsNew=', aggregateRecordsNew ))
        answerStrVotes, reasonVotes = aggregateRecordsNew 

    else:  # Database
        optionId = ''
        userVotes, aggregateRecordsNew, questionVotes = voteDatabase(
            userId, surveyId, questionId, optionId, answerString=answerString, reason=reason )
        logging.debug(LogMessage( 'aggregateRecordsNew=', aggregateRecordsNew ))
        reasonVotes, answerNumVotes, answerStrVotes, optionVotes = aggregateRecordsNew or (None, None, None, None)

    return userVotes, answerStrVotes, reasonVotes, questionVotes


# For budget-question, which has to set 3 answer levels: content, amount, reason
# Caller must specify the old content, so this function can remove or modify the old allocation
def voteBudgetItem( userId, surveyId, questionId, itemOld, itemNew, amountNew, reasonNew ):
    if conf.IS_CLOUD:
        userVoteRecord, aggregateRecordsNew, aggregateRecordsOld, errorMessage = VoteAggregate.voteBudgetItem(
            userId, surveyId, questionId, itemOld, itemNew, amountNew, reasonNew )
        answerStrVotes, answerNumVotes, reasonVotes = aggregateRecordsNew
    else:
        userVoteRecord, answerStrVotes, answerNumVotes, reasonVotes = voteBudgetItemDatabase(
            userId, surveyId, questionId, itemOld, itemNew, amountNew, reasonNew )
        errorMessage = None

    return userVoteRecord, answerStrVotes, answerNumVotes, reasonVotes, errorMessage

def __storeAnswerBudgetItem( userId, surveyId, questionId, itemOld, itemNew, amountNew, reasonNew ):
    # Store answer in user-survey-answers
    userVoteRecord = multi.userAnswers.retrieveOrCreate( surveyId, userId )
    logging.debug(LogMessage('userVoteRecord=', userVoteRecord))

    # Check total allocation inside vote-transaction, because limit depends on current user-answers
    # For user-answers, item-content should not be hashed, so that it is displayable in client
    subkeysForBudgetItemOld = [ SubKey(value=questionId, isId=True) , SubKey(value=itemOld, isId=True) ]
    subkeysForBudgetItemNew = [ SubKey(value=questionId, isId=True) , SubKey(value=itemNew, isId=True) ]
    answerOld = multi.userAnswers.removeAnswer( userVoteRecord, SubKey.subkeysToStrings(subkeysForBudgetItemOld) )
    questionAnswers = multi.userAnswers.getQuestionAnswers( userVoteRecord, questionId )
    if questionAnswers:  questionAnswers.pop( itemOld, None )
    logging.debug(LogMessage('answerOld=', answerOld))

    if amountNew and ( 0 < amountNew ):
        # For new allocation, set an index-number, so that allocation order can be sorted consistently
        answerNew = multi.userAnswers.setAnswer( userVoteRecord, SubKey.subkeysToStrings(subkeysForBudgetItemNew), amountNew, reasonNew, setId=True, id=answerOld.id )
        logging.debug(LogMessage('userVoteRecord=', userVoteRecord))

    allocationSum = multi.userAnswers.budgetSum( userVoteRecord, questionId ) 
    if ( allocationSum < 0 ) or ( 100 < allocationSum ):  raise ValueError( 'allocationSum={}'.format(allocationSum) ) 

    userVoteRecord.put()
    return userVoteRecord


# For list-question, caller must specify the old content, so this function can remove or modify the old answer
def voteListItem( userId, surveyId, questionId, itemOld, itemNew, reasonNew, maxItems=5 ):
    if conf.IS_CLOUD:
        userVoteRecord, aggregateRecordsNew, aggregateRecordsOld, errorMessage = VoteAggregate.voteListItem(
            userId, surveyId, questionId, itemOld, itemNew, reasonNew, maxItems=maxItems )
        answerStrVotes, reasonVotes = aggregateRecordsNew
    else:
        userVoteRecord, aggregateRecordsNew, errorMessage = voteListItemDatabase( userId, surveyId, questionId, itemOld, itemNew, reasonNew, maxItems=maxItems )
        reasonVotes, answerNumVotes, answerStrVotes, optionVotes = aggregateRecordsNew  if aggregateRecordsNew  else (None, None, None, None)

    return userVoteRecord, answerStrVotes, reasonVotes, errorMessage

def __storeAnswerListItem( userId, surveyId, questionId, itemOld, itemNew, reasonNew, maxItems=5 ):

    logging.debug(LogMessage('userId=', userId, 'surveyId=', surveyId, 'questionId=', questionId, 'itemOld=', itemOld, 'itemNew=', itemNew, 'reasonNew=', reasonNew))

    # Store answer in user-survey-answers
    userVoteRecord = multi.userAnswers.retrieveOrCreate( surveyId, userId )
    logging.debug(LogMessage('userVoteRecord=', userVoteRecord))

    # Check for duplicate new item
    questionAnswers = multi.userAnswers.getQuestionAnswers( userVoteRecord, questionId )
    if ( itemOld != itemNew ) and questionAnswers and ( itemNew in questionAnswers ):  return None, conf.DUPLICATE

    # Remove old reason
    # For user-answers, item-subkey should not be hashed, so that it is displayable in client
    subkeysOld = [ SubKey(value=questionId, isId=True) , SubKey(value=itemOld, isId=True) ]
    subkeysNew = [ SubKey(value=questionId, isId=True) , SubKey(value=itemNew, isId=True) ]
    logging.debug(LogMessage('subkeysToStrings(subkeysOld)=', SubKey.subkeysToStrings(subkeysOld) ))
    answerOld = multi.userAnswers.removeAnswer( userVoteRecord, SubKey.subkeysToStrings(subkeysOld) )
    logging.debug(LogMessage('answerOld=', answerOld))
    # Remove old item
    if questionAnswers:  questionAnswers.pop( itemOld, None )
    logging.debug(LogMessage('userVoteRecord=', userVoteRecord))
    # Set new item
    if not multi.userAnswers.answerIsEmpty( itemNew, reasonNew ):
        # For new item, set an index-number, so that item order can be sorted consistently
        content = None
        answerNew = multi.userAnswers.setAnswer( userVoteRecord, SubKey.subkeysToStrings(subkeysNew), content, reasonNew, setId=True, id=answerOld.id )
        logging.debug(LogMessage('userVoteRecord=', userVoteRecord))

    # Check number of items inside vote-transaction, because limit depends on current user-answers
    numItems = multi.userAnswers.numItems( userVoteRecord, questionId )
    if ( maxItems < numItems ):  raise ValueError( 'maxItems={} < numItems={}'.format(maxItems, numItems) )

    userVoteRecord.put()
    return userVoteRecord, None  # Null error-message



# For displaying results
TopVotes = collections.namedtuple( 'TopVotes', ['id','content','votes','median','allocation'], defaults=[None,None] )  # median and allocation are optional

def retrieveRatingQuestionTopReasons( surveyId, questionId, optionId, rating, cursor=None, maxRecords=5 ):
    if conf.IS_CLOUD:
        parentSubkeys = [ SubKey(questionId, isId=True) , SubKey(optionId, isId=True) , SubKey(rating, isNumber=True) ]
        reasonVoteCounts, cursor, more = VoteAggregate.retrieveTopByVotes( surveyId, parentSubkeys, cursor=cursor, maxRecords=maxRecords )
        reasonVoteCounts = [ TopVotes(id=r.lastSubkeyHash(), content=r.lastSubkeyText, votes=r.voteCount)  for r in reasonVoteCounts ]
    else:  # Database
        cursor = cursor or 0
        answerString = ''
        answerNumber = rating
        reasonVoteCounts, cursor, more = retrieveTopReasonsByVotesDatabase( surveyId, questionId, optionId, answerString, answerNumber, maxRecords=maxRecords, cursor=cursor )
        reasonVoteCounts = [ TopVotes(id=r.reasonHash, content=r.reason, votes=r.voteCount)  for r in reasonVoteCounts  if r.reason ]
    return reasonVoteCounts, cursor, more

def retrieveTextQuestionTopAnswers( surveyId, questionId, maxRecords=5, cursor=None ):
    if conf.IS_CLOUD:
        parentSubkeys = [ SubKey(questionId, isId=True) ]
        answerVoteCounts, cursor, more = VoteAggregate.retrieveTopByVotes( surveyId, parentSubkeys, maxRecords=5, cursor=cursor )
        answerVoteCounts = [ TopVotes(id=a.lastSubkeyHash(), content=a.lastSubkeyText, votes=a.voteCount)  for a in answerVoteCounts ]
    else:  # Database
        optionId = ''
        answerVoteCounts, cursor, more = retrieveTopAnswersStrByVotesDatabase( surveyId, questionId, optionId, maxRecords=maxRecords, cursor=cursor )
        answerVoteCounts = [ TopVotes(id=a.answerStringHash, content=a.answerString, votes=a.voteCount)  for a in answerVoteCounts ]
    return answerVoteCounts, cursor, more

def retrieveTextQuestionTopReasons( surveyId, questionId, answerId, maxRecords=5 ):
    if conf.IS_CLOUD:
        parentSubkeys = [ SubKey(questionId, isId=True) , SubKey(answerId, isHash=True) ] 
        reasonVoteCounts, cursor, more = VoteAggregate.retrieveTopByVotes( surveyId, parentSubkeys, maxRecords=maxRecords ) 
        reasonVoteCounts = [ TopVotes(id=r.lastSubkeyHash(), content=r.lastSubkeyText, votes=r.voteCount)  for r in reasonVoteCounts ]
    else:  # Database
        answerStringHash = answerId
        reasonVoteCounts, cursor, more = retrieveTopReasonsForAnswerIdByVotesDatabase( surveyId, questionId, answerStringHash, maxRecords=maxRecords )
        reasonVoteCounts = [ TopVotes(id=r.reasonHash, content=r.reason, votes=r.voteCount)  for r in reasonVoteCounts  if r.reason ]
    return reasonVoteCounts, cursor, more

def retrieveBudgetQuestionTopItems( surveyId, questionId, maxRecords=20 ):
    if conf.IS_CLOUD:
        parentSubkeys = [ SubKey(questionId, isId=True) ]
        answerVoteCounts, cursor, more = VoteAggregate.retrieveTopByVotes( surveyId, parentSubkeys, maxRecords=maxRecords )
        answerVoteCounts = [  TopVotes( id=a.lastSubkeyHash(), content=a.lastSubkeyText, votes=a.voteCount, median=a.medianChild() )  for a in answerVoteCounts  ]
    else:  # Database
        optionId = ''
        cursor = 0
        answerNumVoteRecords = storage.RecordDatabase.fetchall( f"""
            select surveyId, questionId, optionId, answerString, answerStringHash ,
              sum( voteCount ) as voteCount,
              json_objectagg( answerNumber, voteCount ) as allocations
             from {TABLE_NAME_VOTE_AGG_PER_ANSWER_NUMBER}
             where surveyId=%s and questionId=%s and optionId=%s
             group by surveyId, questionId, optionId, answerString, answerStringHash
             order by voteCount desc  limit %s offset %s
            """ ,
            parameters=(surveyId, questionId, optionId, maxRecords, cursor) ,
            table=TABLE_NAME_VOTE_AGG_PER_ANSWER_STRING
        )
        logging.warning(LogMessage( 'answerNumVoteRecords=', answerNumVoteRecords ))
        more = ( 0 < len(answerNumVoteRecords) )
        cursor = cursor + maxRecords  if more  else None

        answerVoteCounts = []
        for answerVoteRecord in answerNumVoteRecords:
            logging.warning(LogMessage( 'answerVoteRecord=', answerVoteRecord ))

            allocationToCount = answerVoteRecord.allocations
            logging.warning(LogMessage( 'allocationToCount=', allocationToCount ))

            medianAllocation = stats.medianKey( allocationToCount )
            logging.warning(LogMessage( 'medianAllocation=', medianAllocation ))

            answerVoteCounts.append( TopVotes(
                id=answerVoteRecord.answerStringHash, content=answerVoteRecord.answerString, votes=answerVoteRecord.voteCount, median=medianAllocation
            ) )
            logging.warning(LogMessage( 'answerVoteCounts=', answerVoteCounts ))

    return answerVoteCounts, cursor, more

def retrieveBudgetQuestionTopReasons( surveyId, questionId, itemId, maxRecords=5 ):
    if conf.IS_CLOUD:
        parentSubkeys = [ SubKey(questionId, isId=True) , SubKey(answerId, isHash=True) ]
        reasonVoteCounts, cursor, more = VoteAggregate.retrieveTopByVotes( surveyId, parentSubkeys, maxRecords=maxRecords ) 
        reasonVoteCounts = [  TopVotes( id=r.lastSubkeyHash(), content=r.lastSubkeyText, votes=r.voteCount, allocation=int(r.parentSubkeyText()) )  for r in reasonVoteCounts  ]
    else:  # Database
        answerStringHash = itemId
        reasonVoteCounts, cursor, more = retrieveTopReasonsForAnswerIdByVotesDatabase( surveyId, questionId, answerStringHash, maxRecords=maxRecords )
        reasonVoteCounts = [  TopVotes( id=r.reasonHash, content=r.reason, votes=r.voteCount, allocation=r.answerNumber )  for r in reasonVoteCounts  if r.reason  ]
    return reasonVoteCounts, cursor, more

def retrieveListQuestionTopAnswers( surveyId, questionId, maxRecords=10 ):
    if conf.IS_CLOUD:
        parentSubkeys = [ SubKey(questionId, isId=True) ]
        answerVoteCounts, cursor, more = VoteAggregate.retrieveTopByVotes( surveyId, parentSubkeys, maxRecords=maxRecords )
        answerVoteCounts = [ TopVotes(id=a.lastSubkeyHash(), content=a.lastSubkeyText, votes=a.voteCount)  for a in answerVoteCounts ]
    else:  # Database
        optionId = ''
        answerVoteCounts, cursor, more = retrieveTopAnswersStrByVotesDatabase( surveyId, questionId, optionId, maxRecords=maxRecords )
        answerVoteCounts = [ TopVotes(id=a.answerStringHash, content=a.answerString, votes=a.voteCount)  for a in answerVoteCounts ]
    return answerVoteCounts, cursor, more

def retrieveListQuestionTopReasons( surveyId, questionId, itemId, maxRecords=5 ):
    if conf.IS_CLOUD:
        parentSubkeys = [ SubKey(questionId, isId=True) , SubKey(itemId, isId=True) ] 
        reasonVoteCounts, cursor, more = voteAggregates.retrieveTopByVotes( surveyId, parentSubkeys )
        reasonVoteCounts = [ TopVotes(id=r.lastSubkeyHash(), content=r.lastSubkeyText, votes=r.voteCount)  for r in reasonVoteCounts ]
    else:  # Database
        answerStringHash = itemId
        reasonVoteCounts, cursor, more = retrieveTopReasonsForAnswerIdByVotesDatabase( surveyId, questionId, answerStringHash, maxRecords=maxRecords )
        reasonVoteCounts = [ TopVotes(id=r.reasonHash, content=r.reason, votes=r.voteCount)  for r in reasonVoteCounts  if r.reason ]
    return reasonVoteCounts, cursor, more



def retrieveQuestionVoteAgg( surveyId, questionId ):
    if conf.IS_CLOUD:
        subkeys = [ SubKey(questionId, isId=True) ]
        return VoteAggregate.retrieve( surveyId, subkeys )
    else:  # Database
        return storage.RecordDatabase.fetchone(
            f" select * from {TABLE_NAME_VOTE_AGG_PER_QUESTION} where surveyId=%s and questionId=%s " ,
            parameters=(surveyId, questionId) ,
            table=TABLE_NAME_VOTE_AGG_PER_QUESTION
        )

def retrieveOptionVoteAgg( surveyId, questionId, optionId ):
    if conf.IS_CLOUD:
        subkeys = [ SubKey(questionId, isId=True) , SubKey(optionId, isId=True) ] 
        return VoteAggregate.retrieve( surveyId, subkeys ) 
    else:  # Database
        voteRecords = storage.RecordDatabase.fetchall( f"""
             select * from {TABLE_NAME_VOTE_AGG_PER_ANSWER_NUMBER}
              where surveyId=%s and questionId=%s and optionId=%s
            """ ,
            parameters=(surveyId, questionId, optionId)
        )
        logging.warning(LogMessage( 'voteRecords=', voteRecords ))
        childToVotes = { str(r.answerNumber) : r.voteCount  for r in voteRecords }
        return childToVotes, stats.averageKey( childToVotes ) , stats.medianKey( childToVotes )



# For suggesting higher/lower numeric answers & reasons while user inputs answer
def retrieveTopNumericAnswersAndReasons( surveyId, questionId, optionId, answerNumber=0, reasonStart=None, isBudget=False, maxRecords=3 ):
    if conf.IS_CLOUD:
        subkeys = [ SubKey(questionId, isId=True) , SubKey(optionId, isId=isBudget, doAggregate=True) ]
        return VoteAggregate.retrieveTopNumericAnswersAndReasons( surveyId, subkeys, answer=answerNumber, reasonStart=reasonStart, maxRecords=maxRecords )
    else:
        answerString = optionId  if isBudget  else ''
        if isBudget:  optionId = ''
        return suggestNumericAnswersAndReasonsFromDatabase( surveyId, questionId, optionId, answerString=answerString, answerNumber=answerNumber, reasonStart=reasonStart, maxRecords=maxRecords )

# For suggesting text answers & reasons while user inputs answer
def retrieveTopAnswersAndReasons( surveyId, questionId, inputText=None, maxRecords=3 ):
    if conf.IS_CLOUD:
        subkeys = [ SubKey(questionId, isId=True) ]
        return VoteAggregate.retrieveTopAnswersAndReasons( surveyId, subkeys, inputText=inputText, maxRecords=maxRecords )
    else:
        return suggestAnswersAndReasonsFromDatabase( surveyId, questionId, inputText=inputText, maxRecords=maxRecords )

# For suggesting budget allocations while user inputs answer
def retrieveTopAllocationsAndReasons( surveyId, questionId, inputText=None, maxRecords=3 ):
    if conf.IS_CLOUD:
        subkeys = [ SubKey(questionId, isId=True) ]
        return VoteAggregate.retrieveTopAllocationsAndReasons( surveyId, subkeys, inputText=inputText, maxRecords=maxRecords )
    else:
        return suggestAllocationsAndReasonsFromDatabase( surveyId, questionId, inputText=inputText, maxRecords=maxRecords )



def toClient( record, userId ):
    logging.warning(LogMessage( 'record=', record ))
    if not record:  return None
    data = {
        'id': str( record.key.id() ) ,
        'reason': record.lastSubkeyText  if conf.IS_CLOUD  else record.reason ,
        'answerNumber': record.parentSubkeyText  if conf.IS_CLOUD  else record.answerNumber ,
        'answerString': record.grandparentSubkeyText  if conf.IS_CLOUD  else record.answerString ,
        'words': ' '.join( record.words )  if record.words  else '' ,
        'votes': record.voteCount ,
        'score': record.score ,
    }
    return data


