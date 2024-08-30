# Data record classes

from multi.configMulti import conf
# Import external modules
import base64
from collections import namedtuple
import datetime
import hashlib
import json
import logging
import re
import time
# Import app modules
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
#  In request-for-problems question, store problem with/out votes, find top / word-matching problems

if conf.IS_CLOUD:
    from google.appengine.ext import ndb

    # Record for storing problem / proposal / reason
    class Content( ndb.Model ):

        surveyId = ndb.StringProperty()   # To verify answer belongs to survey
        questionId = ndb.StringProperty()   # To verify answer belongs to question
        parentKey = ndb.StringProperty()  # Parent content's key

        content = ndb.StringProperty()
        words = ndb.StringProperty( repeated=True )  # For matching input-words to make suggestions
        proOrCon = ndb.StringProperty()  # Value in { conf.PRO, conf.CON }

        creator = ndb.StringProperty()
        timeCreated = ndb.IntegerProperty( default=0 )
        timeModified = ndb.DateTimeProperty( auto_now=True )

        hasResponse = ndb.BooleanProperty()
        numPros = ndb.IntegerProperty( default=0 )
        numCons = ndb.IntegerProperty( default=0 )
        voteCount = ndb.IntegerProperty( default=0 )
        score = ndb.FloatProperty( default=0 )
        maxChildVotes = ndb.IntegerProperty( default=0 )
        
        @staticmethod
        def create( surveyId, questionId, subkeys, content=None, creator=None, proOrCon=None ):
            parentKey = str( subkeys[-1] )  if ( 0 < len(subkeys) )  else None
            record = Content( surveyId=surveyId, questionId=questionId, parentKey=parentKey, creator=creator, proOrCon=proOrCon )
            record.setContent( content )
            return record

        def setContent( self, content ):
            self.content = content
            # Index content words
            self.words = multi.shared.textToTuples( self.content )

        @staticmethod
        def exists( surveyId, questionId, subkeys, *, content ):
            parentKey = str( subkeys[-1] )  if ( 0 < len(subkeys) )  else None
            existingContent = Content.query(
                Content.surveyId==str(surveyId) , Content.questionId==str(questionId) , Content.parentKey==parentKey , Content.content==content ).fetch()
            logging.debug(LogMessage('existingContent=', existingContent))
            return bool( existingContent )

        @staticmethod
        def retrieve( surveyId, questionId, subkeys, contentId=None ):
            parentKey = str( subkeys[-1] )  if ( 0 < len(subkeys) )  else None
            contentRecord = Content.get_by_id( contentId )
            if not contentRecord:  return None
            if ( contentRecord.surveyId != surveyId ): raise KeyError('surveyId does not match')
            if ( contentRecord.questionId != questionId ):  raise KeyError('questionId does not match')
            if ( contentRecord.parentKey != parentKey ):  raise KeyError('parentKey does not match')
            return contentRecord

        def incrementNumProsOrCons( self, proOrCon, increment ):
            if ( proOrCon is None ):  return
            elif ( proOrCon == conf.PRO ):  self.setNumProsAndCons( (self.numPros + increment), self.numCons )
            elif ( proOrCon == conf.CON ):  self.setNumProsAndCons( self.numPros, (self.numCons + increment) )
            else:  raise ValueError( 'proOrCon is invalid' )

        def setNumProsAndCons( self, newNumPros, newNumCons ):
            self.numPros = max( 0, newNumPros )
            self.numCons = max( 0, newNumCons )
            self.voteCount = self.numPros - self.numCons
            self.score = multi.shared.scoreDiscountedByLength( self.voteCount, self.content )

        def incrementVoteCount( self, increment ):  self.setVoteCount( self.voteCount + increment )

        def setVoteCount( self, newVoteCount ):
            self.voteCount = max( 0, newVoteCount )
            self.score = multi.shared.scoreDiscountedByLength( self.voteCount, self.content )

        def toClient( self, userId ):
            result = {
                'id': str( self.key.id() ) ,
                'parentKey': self.parentKey ,
                'mine': ( self.creator == userId ) ,
                'content': self.content ,
                'words': ' '.join( self.words )  if self.words  else '' ,
                'hasResponse': self.hasResponse ,
                'votes': self.voteCount ,
                'score': self.score ,
            }
            if self.proOrCon:  result['proOrCon'] = self.proOrCon
            if self.numPros is not None:  result['pros'] = self.numPros
            if self.numCons is not None:  result['cons'] = self.numCons
            return result



        #####################################################################################################
        # Methods to retrieve top content-records

        # Returns records, cursor, more:boolean
        @staticmethod
        def retrieveTopContent( surveyId, questionId, subkeys, maxRecords=3, cursor=None, proOrCon=None ):
            future = __retrieveTopContentAsync( surveyId, questionId, subkeys, maxRecords=maxRecords, cursor=cursor, proOrCon=proOrCon )
            return future.get_result()

        # Returns future producing 1 batch of records & next-page-cursor 
        @staticmethod
        def __retrieveTopContentAsync( surveyId, questionId, subkeys, maxRecords=3, cursor=None, proOrCon=None ):

            parentKey = str( subkeys[-1] )  if ( 0 < len(subkeys) )  else None

            if proOrCon:
                return Content.query( 
                    Content.surveyId==str(surveyId) , Content.questionId==str(questionId) , Content.parentKey==parentKey , Content.proOrCon==proOrCon ).order( 
                    -Content.score ).fetch_page_async( maxRecords, start_cursor=cursor )
            else:
                return Content.query( 
                    Content.surveyId==str(surveyId) , Content.questionId==str(questionId) , Content.parentKey==parentKey ).order( 
                    -Content.score ).fetch_page_async( maxRecords, start_cursor=cursor )


        @staticmethod
        def retrieveTopProblems( surveyId, questionId, maxRecords=3, cursor=None ):
            records, cursor, more = Content.query( 
                Content.surveyId==str(surveyId) , Content.questionId==str(questionId) , Content.parentKey==None ).order( -Content.maxChildVotes ).fetch_page( maxRecords, start_cursor=cursor )
            logging.debug(LogMessage('records=', records, 'cursor=', cursor, 'more=', more, 'v6'))
            return records, cursor, more


        # Returns series[ content-record ]
        @staticmethod
        def retrieveTopMatchingContent( surveyId, questionId, subkeys, contentStart ):
            inputWords = multi.shared.tokenizeText( contentStart )
            if conf.isDev:  logging.debug(LogMessage('inputWords=', inputWords))

            parentKey = str( subkeys[-1] )  if ( 0 < len(subkeys) )  else None

            contentRecordFutures = []
            if inputWords and ( 0 < len(inputWords) ):
                # Retrieve top-voted content-records matching last input-word 
                # Results will be collected & match-scored in client 
                lastWord = inputWords[ -1 ]
                contentRecordFutures.append(
                    Content.query(
                        Content.surveyId==str(surveyId), Content.questionId==str(questionId) , Content.parentKey==parentKey , Content.words==lastWord
                        ).order( -Content.score ).fetch_async( 1 )  )
                # Retrieve for last input-word-pair 
                if ( 2 <= len(inputWords) ):
                    lastTuple = ' '.join( inputWords[-2:] )
                    contentRecordFutures.append(
                        Content.query(
                            Content.surveyId==str(surveyId), Content.questionId==str(questionId) , Content.parentKey==parentKey , Content.words==lastTuple
                            ).order( -Content.score ).fetch_async( 1 )  )

            # De-duplicate records, since both word & tuple-top-suggestion may be the same 
            recordsUnique = { }
            for future in contentRecordFutures:
                if future:
                    for record in future.get_result():
                        if record:
                            recordsUnique[ record.key.id() ] = record
            if conf.isDev:  logging.debug(LogMessage('recordsUnique=', recordsUnique))

            return recordsUnique.values()


###########################################################################################
# Database

if not conf.IS_CLOUD:

    PROBLEM = 'problem'
    SOLUTION = 'solution'
    REASON = 'reason'
    CONTENT_TYPES = [ PROBLEM, SOLUTION, REASON ]

    TABLE_NAME_CONTENT = 'contents'
    storage.databaseInitialize( f"""
        create table if not exists {TABLE_NAME_CONTENT} (
         id  int  auto_increment  primary key  not null ,
         surveyId  int  not null ,
         questionId  varchar(5)  not null ,
         parentKey  int  not null ,
         content  text  not null ,
         words  json  not null  default('[]') ,
         type  varchar(10)  not null ,
         proOrCon  varchar(3)  not null ,
         hasResponse  boolean  not null  default false ,

         creator  varchar({user.const.ID_COOKIE_LENGTH})  not null ,
         timeCreated  datetime  not null  default current_timestamp ,
         timeModified  datetime  not null  on update current_timestamp  default current_timestamp ,

         foreign key (surveyId) references {multi.survey.TABLE_NAME}(id) ,
         key (  ( cast(words as char(100) array) )  )
        ) ENGINE=InnoDB
    """ )
    # type: { "problem", "solution", "reason" }
    # proOrCon: { "pro", "con" }
    # parentKey can be null/zero, therefore not an existing id, not a valid foreign-key value
    # Because "=null" fails in sql, have to check sql code for null values and convert to "is null"
    #  Instead, disallow null, allow empty-string or zero

    TABLE_NAME_VOTE = 'user_content_vote'
    storage.databaseInitialize( f"""
        create table if not exists {TABLE_NAME_VOTE} (
         userId  varchar({user.const.ID_COOKIE_LENGTH})  not null ,
         surveyId  int  not null ,
         questionId  varchar(4)  not null ,
         parentKey  int  not null ,
         contentId  int  not null ,

         foreign key (surveyId) references {multi.survey.TABLE_NAME}(id) ,
         primary key (userId, surveyId, questionId, parentKey, contentId)
        )
    """ )

    TABLE_NAME_VOTE_AGG_PER_REASON = 'vote_agg_per_content_reason'
    if not storage.viewExists( TABLE_NAME_VOTE_AGG_PER_REASON ):
        storage.databaseInitialize( f"""
            create view {TABLE_NAME_VOTE_AGG_PER_REASON} as select
              C.surveyId as surveyId, C.questionId as questionId, C.id as contentId, C.type as contentType, C.proOrCon as proOrCon, C.parentKey as parentKey,
              count(*) as voteCount,
              if( C.proOrCon='pro', count(*), 0 ) - if( C.proOrCon='con', count(*), 0 )  as voteCountSigned ,
              cast(count(*) as decimal) / greatest( 1.0, cast(length(C.content) as decimal)/{float(conf.CHAR_LENGTH_UNIT)} ) as score
             from {TABLE_NAME_VOTE} as V join {TABLE_NAME_CONTENT} as C
             where V.surveyId=C.surveyId and V.questionId=C.questionId and V.contentId=C.id and C.type='{REASON}'
             group by C.surveyId, C.questionId, C.id
            """
        )

    TABLE_NAME_VOTE_AGG_PER_SOLUTION = 'vote_agg_per_content_solution'
    if not storage.viewExists( TABLE_NAME_VOTE_AGG_PER_SOLUTION ):
        storage.databaseInitialize( f"""
            create view {TABLE_NAME_VOTE_AGG_PER_SOLUTION} as select
              C.surveyId as surveyId, C.questionId as questionId, C.id as contentId, C.type as contentType, C.parentKey as parentKey,
              sum( V.voteCountSigned ) as voteCount,
              cast( sum(V.voteCountSigned) as decimal ) / greatest( 1.0, cast(length(C.content) as decimal)/{float(conf.CHAR_LENGTH_UNIT)} ) as score
             from {TABLE_NAME_VOTE_AGG_PER_REASON} as V join {TABLE_NAME_CONTENT} as C
             where V.surveyId=C.surveyId and V.questionId=C.questionId and V.parentKey=C.id
             group by C.surveyId, C.questionId, C.id
            """
        )

    TABLE_NAME_VOTE_AGG_PER_PROBLEM = 'vote_agg_per_content_problem'
    if not storage.viewExists( TABLE_NAME_VOTE_AGG_PER_PROBLEM ):
        storage.databaseInitialize( f"""
            create view {TABLE_NAME_VOTE_AGG_PER_PROBLEM} as select
              C.surveyId as surveyId, C.questionId as questionId, C.id as contentId, C.type as contentType, C.parentKey as parentKey,
              max( V.voteCount ) as maxChildVotes,
              cast(max(V.voteCount) as decimal) / greatest( 1.0, cast(length(C.content) as decimal)/{float(conf.CHAR_LENGTH_UNIT)} ) as score
             from {TABLE_NAME_VOTE_AGG_PER_SOLUTION} as V join {TABLE_NAME_CONTENT} as C
             where V.surveyId=C.surveyId and V.questionId=C.questionId and V.parentKey=C.id
             group by C.surveyId, C.questionId, C.id
            """
        )

    def retrieveDatabase( contentId ):
        return storage.RecordDatabase.retrieve( TABLE_NAME_CONTENT, contentId )

    def createDatabase( surveyId, questionId, subkeys, *, content, creator, proOrCon='' ):
        contentType = CONTENT_TYPES[ len(subkeys) ]
        parentKey = int( subkeys[-1] or 0 )  if ( 0 < len(subkeys) )  else 0

        # Mark parent responded
        if parentKey:
            parentRecord = storage.get_by_id( TABLE_NAME_CONTENT, parentKey )
            if not parentRecord.hasResponse:
                parentRecord.hasResponse = True
                parentRecord.put()

        # Store new content
        proOrCon = proOrCon or ''  # Allow empty field, but not null since that cannot be used for queries
        record = storage.RecordDatabase.create( table=TABLE_NAME_CONTENT,
            fields={ 'surveyId':surveyId, 'questionId':questionId, 'type':contentType, 'parentKey':parentKey,
                'proOrCon':proOrCon, 'words':[], 'creator':creator } ,
            jsons=['words'] )
        setContent( record, content )
        return record

    def setContentDatabase( record, content ):
        record.content = content
        # Index content words
        words = multi.shared.tokenizeText( record.content )
        words = words[ 0 : conf.MAX_WORDS_TO_INDEX ]  # Limit number of words indexed
        record.words = text.tuples( words, maxSize=conf.MAX_COMPOUND_WORD_LENGTH )

    def existsDatabase( surveyId, questionId, subkeys, *, content ):
        parentKey = int( subkeys[-1] or 0 )  if ( 0 < len(subkeys) )  else 0
        results = storage.RecordDatabase.fetchall(
            f" select id from contents  where surveyId=%s and questionId=%s and parentKey=%s and content=%s" ,
            parameters=(surveyId, questionId, parentKey, content)
        )
        return bool( results )



    def voteSolutionReasonDatabase( userId, surveyId, questionId, problemId, solutionId, reasonId, reasonIdOld ):
        problemId = problemId or 0
        solutionId = solutionId or 0
        logging.debug(LogMessage('userId=', userId, 'surveyId=', surveyId, 'questionId=', questionId, 'problemId=', problemId, 'solutionId=', solutionId, 'reasonId=', reasonId, 'reasonIdOld=', reasonIdOld))

        # Mark reason responded (if voting yes)
        if reasonId:
            parentRecord = storage.get_by_id( TABLE_NAME_CONTENT, reasonId )
            if not parentRecord.hasResponse:
                parentRecord.hasResponse = True
                parentRecord.put()

        # Remove all user's votes for reasons for this proposal
        storage.databaseExecute( f"""
            delete from {TABLE_NAME_VOTE} where
             userId=%s and surveyId=%s and questionId=%s and parentKey=%s
            """ ,
            parameters=( userId, surveyId, questionId, solutionId ) ,
        )

        # Insert new user vote for reason
        if reasonId:
            storage.databaseExecute( f"""
                insert into {TABLE_NAME_VOTE} (userId, surveyId, questionId, parentKey, contentId)
                  values (%s, %s, %s, %s, %s)
                """ ,
                parameters=( userId, surveyId, questionId, solutionId, reasonId )
            )

        # Get updated vote counts
        contentRecords = []
        contentRecords.append(  storage.RecordDatabase.fetchone( f"""
            select * from {TABLE_NAME_VOTE_AGG_PER_PROBLEM} as A join {TABLE_NAME_CONTENT} as C
              where A.contentId=C.id and C.id=%s
            """ ,
            parameters=[ problemId ]
        )  )
        contentRecords.append(  storage.RecordDatabase.fetchone( f"""
            select * from {TABLE_NAME_VOTE_AGG_PER_PROBLEM} as A join {TABLE_NAME_CONTENT} as C
              where A.contentId=C.id and C.id=%s
            """ ,
            parameters=[ problemId ]
        )  )
        contentRecords.append(  storage.RecordDatabase.fetchone( f"""
            select * from {TABLE_NAME_VOTE_AGG_PER_REASON} as A join {TABLE_NAME_CONTENT} as C
              where A.contentId=C.id and C.id=%s
            """ ,
            parameters=[ reasonId ]
        )  )
        contentRecords.append(  storage.RecordDatabase.fetchone( f"""
            select * from {TABLE_NAME_VOTE_AGG_PER_REASON} as A join {TABLE_NAME_CONTENT} as C
              where A.contentId=C.id and C.id=%s
            """ ,
            parameters=[ reasonIdOld ]
        )  )

        return contentRecords



    # Returns records, cursor
    def retrieveTopReasonsDatabase( surveyId, questionId, problemId, solutionId, maxRecords=3, cursor=0, proOrCon='' ):
        cursor = cursor or 0
        problemId = problemId or 0
        solutionId = solutionId or 0
        # Order by score and id, to keep sort order consistent when scores are null
        records = storage.RecordDatabase.fetchall( f"""
            select * from {TABLE_NAME_VOTE_AGG_PER_REASON} as V right join {TABLE_NAME_CONTENT} as C
             on V.surveyId=C.surveyId and V.questionId=C.questionId and V.contentId=C.id
             where C.surveyId=%s and C.questionId=%s and C.parentKey=%s and C.proOrCon=%s
             order by if(V.score is null, 0, score) , C.id desc  limit %s offset %s
            """ ,
            parameters=(surveyId, questionId, solutionId, proOrCon, maxRecords, cursor) ,
            table=TABLE_NAME_CONTENT
        )
        logging.warning(LogMessage( 'records=', records ))
        return records, cursor + len(records), ( 0 < len(records) )

    def retrieveTopSolutionsDatabase( surveyId, questionId, problemId, maxRecords=3, cursor=0 ):
        cursor = cursor or 0
        problemId = problemId or 0
        records = storage.RecordDatabase.fetchall( f"""
            select * from {TABLE_NAME_VOTE_AGG_PER_SOLUTION} as V right join {TABLE_NAME_CONTENT} as C
             on V.surveyId=C.surveyId and V.questionId=C.questionId and V.contentId=C.id
             where C.surveyId=%s and C.questionId=%s and C.parentKey=%s
             order by if(V.score is null, 0, score) , C.id desc  limit %s offset %s
            """ ,
            parameters=(surveyId, questionId, problemId, maxRecords, cursor) ,
            table=TABLE_NAME_CONTENT
        )
        logging.warning(LogMessage( 'records=', records ))
        return records, cursor + len(records), ( 0 < len(records) )

    def retrieveTopProblemsDatabase( surveyId, questionId, maxRecords=3, cursor=0 ):
        cursor = cursor or 0
        records = storage.RecordDatabase.fetchall( f"""
            select * from {TABLE_NAME_VOTE_AGG_PER_PROBLEM} as V right join {TABLE_NAME_CONTENT} as C
             on V.surveyId=C.surveyId and V.questionId=C.questionId and V.contentId=C.id
             where C.surveyId=%s and C.questionId=%s and (C.parentKey=0 or C.parentKey is null)
             order by if(V.maxChildVotes is null, 0, V.maxChildVotes) , C.id desc  limit %s offset %s
            """ ,
            parameters=(surveyId, questionId, maxRecords, cursor) ,
            table=TABLE_NAME_CONTENT
        )
        logging.warning(LogMessage( 'records=', records ))
        return records, cursor + len(records), ( 0 < len(records) )



    def suggestTopMatchingReasonsDatabase( surveyId, questionId, problemId, solutionId, contentStart ):
        problemId = problemId or 0
        solutionId = solutionId or 0
        inputWords = multi.shared.tokenizeText( contentStart )
        if conf.isDev:  logging.debug(LogMessage('inputWords=', inputWords))

        contentRecords = []
        if inputWords and ( 0 < len(inputWords) ):
            # Retrieve top-voted content-records matching last input-word / tuple
            # Results will be collected & match-scored in client 
            lastWords = [ inputWords[-1] ]
            if ( 2 <= len(inputWords) ):  lastWords.append( ' '.join(inputWords[-2:]) )
            contentRecords = storage.RecordDatabase.fetchall( f"""
                select C.* , V.score
                 from {TABLE_NAME_CONTENT} as C join {TABLE_NAME_VOTE_AGG_PER_REASON} as V
                 where C.surveyId=V.surveyID and C.questionId=V.questionId and C.id=V.contentId and
                  C.surveyId=%s and C.questionId=%s and C.parentKey=%s and json_overlaps(C.words, %s)
                 order by V.score desc  limit 1
                """ ,
                parameters=( surveyId, questionId, solutionId, json.dumps(lastWords) )
            )
        return contentRecords

    def suggestTopMatchingSolutionsDatabase( surveyId, questionId, problemId, contentStart ):
        problemId = problemId or 0
        inputWords = multi.shared.tokenizeText( contentStart )
        if conf.isDev:  logging.debug(LogMessage('inputWords=', inputWords))

        contentRecords = []
        if inputWords and ( 0 < len(inputWords) ):
            # Retrieve top-voted content-records matching last input-word / tuple
            # Results will be collected & match-scored in client 
            lastWords = [ inputWords[-1] ]
            if ( 2 <= len(inputWords) ):  lastWords.append( ' '.join(inputWords[-2:]) )
            contentRecords = storage.RecordDatabase.fetchall( f"""
                select C.* from {TABLE_NAME_CONTENT} as C join {TABLE_NAME_VOTE_AGG_PER_SOLUTION} as V
                 where C.surveyId=V.surveyID and C.questionId=V.questionId and C.id=V.contentId and
                  C.surveyId=%s and C.questionId=%s and C.parentKey=%s and json_overlaps(C.words, %s)
                 order by V.score desc  limit 1
                """ ,
                parameters=( surveyId, questionId, problemId, json.dumps(lastWords) )
            )
        return contentRecords

    def suggestTopMatchingProblemsDatabase( surveyId, questionId, contentStart ):
        inputWords = multi.shared.tokenizeText( contentStart )
        if conf.isDev:  logging.debug(LogMessage('inputWords=', inputWords))

        contentRecords = []
        if inputWords and ( 0 < len(inputWords) ):
            # Retrieve top-voted content-records matching last input-word / tuple
            # Results will be collected & match-scored in client 
            lastWords = [ inputWords[-1] ]
            if ( 2 <= len(inputWords) ):  lastWords.append( ' '.join(inputWords[-2:]) )
            contentRecords = storage.RecordDatabase.fetchall( f"""
                select C.* from {TABLE_NAME_CONTENT} as C join {TABLE_NAME_VOTE_AGG_PER_PROBLEM} as V
                 where C.surveyId=V.surveyID and C.questionId=V.questionId and C.id=V.contentId and
                  C.surveyId=%s and C.questionId=%s and C.parentKey=%s and json_overlaps(C.words, %s)
                 order by V.maxChildVotes desc  limit 1
                """ ,
                parameters=( surveyId, questionId, 0, json.dumps(lastWords) )
            )
        return contentRecords
        

###########################################################################################
# Uniform interface

def create( surveyId, questionId, subkeys, content=None, creator=None, proOrCon=None ):
    if conf.IS_CLOUD:  return Content.create( surveyId, questionId, subkeys, content=content, creator=creator, proOrCon=proOrCon )
    else:              return createDatabase( surveyId, questionId, subkeys, content=content, creator=creator, proOrCon=proOrCon )

def setContent( record, content ):
    if conf.IS_CLOUD:  record.setContent( content )
    else:              setContentDatabase( record, content )

def exists( surveyId, questionId, subkeys, *, content ):
    if conf.IS_CLOUD:  return Content.exists( surveyId, questionId, subkeys, content=content )
    else:              return existsDatabase( surveyId, questionId, subkeys, content=content )

def retrieve( surveyId, questionId, subkeys, contentId=None ):
    contentRecord = Content.get_by_id( contentId )  if conf.IS_CLOUD  else  storage.RecordDatabase.retrieve( TABLE_NAME_CONTENT, contentId )
    if not contentRecord:  return None

    if ( contentRecord.surveyId != surveyId ): raise KeyError('surveyId does not match')
    if ( contentRecord.questionId != questionId ):  raise KeyError('questionId does not match')

    parentKey = subkeys[-1]  if ( 0 < len(subkeys) )  else None
    if not conf.IS_CLOUD:  parentKey = parentKey or 0
    if ( str(contentRecord.parentKey) != str(parentKey) ):  raise KeyError( f'parentKey={parentKey}:{type(parentKey)} does not match contentRecord.parentKey={contentRecord.parentKey}:{type(contentRecord.parentKey)}' )

    return contentRecord

def incrementNumProsOrCons( record, proOrCon, increment ):
    if ( proOrCon is None ):  return
    elif ( proOrCon == conf.PRO ):  setNumProsAndCons( record, (record.numPros + increment), record.numCons )
    elif ( proOrCon == conf.CON ):  setNumProsAndCons( record, record.numPros, (record.numCons + increment) )
    else:  raise ValueError( 'proOrCon is invalid' )

def setNumProsAndCons( record, newNumPros, newNumCons ):
    # Using this method, vote count and score can be negative
    record.numPros = max( 0, newNumPros )
    record.numCons = max( 0, newNumCons )
    record.voteCount = record.numPros - record.numCons
    record.score = multi.shared.scoreDiscountedByLength( record.voteCount, record.content )

def incrementVoteCount( record, increment ):  setVoteCount( record, record.voteCount + increment )

def setVoteCount( record, newVoteCount ):
    # Using this method, vote count and score are positive
    record.voteCount = max( 0, newVoteCount )
    record.score = multi.shared.scoreDiscountedByLength( record.voteCount, record.content )


def toClient( record, userId ):
    if not record:  return None
    result = {
        'id': str( record.key.id() ) ,
        'parentKey': record.parentKey ,
        'mine': ( record.creator == userId ) ,
        'content': record.content ,
        'words': ' '.join( record.words )  if record.words  else '' ,
        'hasResponse': record.hasResponse ,
        'votes': record.voteCount or 0 ,
        'score': record.score or 0 ,
    }
    if record.proOrCon:  result['proOrCon'] = record.proOrCon
    if record.numPros is not None:  result['pros'] = record.numPros
    if record.numCons is not None:  result['cons'] = record.numCons
    return result



def retrieveTopReasons( surveyId, questionId, problemId, solutionId, maxRecords=3, cursor=None, proOrCon=None ):
    if conf.IS_CLOUD:
        records, cursor, more = Content.retrieveTopContent( surveyId, questionId, [problemId, solutionId], maxRecords=maxRecords, cursor=cursor, proOrCon=proOrCon )
    else:
        records, cursor, more = retrieveTopReasonsDatabase( surveyId, questionId, problemId, solutionId, maxRecords=maxRecords, cursor=cursor, proOrCon=proOrCon )
    return records, cursor, more

def retrieveTopSolutions( surveyId, questionId, problemId, maxRecords=3, cursor=None ):
    if conf.IS_CLOUD:
        records, cursor, more = Content.retrieveTopContent( surveyId, questionId, [problemId], maxRecords=maxRecords, cursor=cursor )
    else:
        records, cursor, more = retrieveTopSolutionsDatabase( surveyId, questionId, problemId, maxRecords=maxRecords, cursor=cursor )
    return records, cursor, more

def retrieveTopProblems( surveyId, questionId, maxRecords=3, cursor=None ):
    if conf.IS_CLOUD:
        records, cursor, more = Content.retrieveTopProblems( surveyId, questionId, maxRecords=maxRecords, cursor=cursor )
    else:
        records, cursor, more = retrieveTopProblemsDatabase( surveyId, questionId, maxRecords=maxRecords, cursor=cursor )
    return records, cursor, more


# Returns series[ content-record ]
def retrieveTopMatchingReasons( surveyId, questionId, problemId, solutionId, contentStart ):
    if conf.IS_CLOUD:  return Content.retrieveTopMatchingContent( surveyId, questionId, [problemId, solutionId], contentStart )
    else:              return suggestTopMatchingReasonsDatabase( surveyId, questionId, problemId, solutionId, contentStart )

def retrieveTopMatchingSolutions( surveyId, questionId, problemId, contentStart ):
    if conf.IS_CLOUD:  return Content.retrieveTopMatchingContent( surveyId, questionId, [problemId], contentStart )
    else:              return suggestTopMatchingSolutionsDatabase( surveyId, questionId, problemId, contentStart )

def retrieveTopMatchingProblems( surveyId, questionId, contentStart ):
    if conf.IS_CLOUD:  return Content.retrieveTopMatchingContent( surveyId, questionId, [], contentStart )
    else:              return suggestTopMatchingProblemsDatabase( surveyId, questionId, contentStart )

