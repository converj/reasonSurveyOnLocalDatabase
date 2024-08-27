# Import external modules
import logging
import os
import sys
# Import app modules
from constants import Constants


# Call this during unit-tests, to configure visible logs
def logForUnitTest():
    logging.basicConfig( stream=sys.stdout, level=logging.DEBUG, format='%(filename)s %(funcName)s():  %(message)s' )


# Constants
const = Constants()

const.pythonVersion = sys.version_info[0]

const.IS_CLOUD = False

const.isDev = os.path.isfile('configurationDev.py')
if const.isDev:  import configurationDev
logging.warn( f'const.isDev={const.isDev}' )

if const.isDev:
    logging.basicConfig( stream=sys.stdout, level=logging.DEBUG, format='\n%(filename)s %(funcName)s():  %(message)s' )
else:
    logging.getLogger().setLevel( logging.WARNING )

const.SITE_NAME = 'Converj'
const.SITE_URL = 'https://converj.net'   # Public website, since current-website can be referenced as "/"

const.COOKIE_FIELD_SIGNATURE = 'signature'
const.COOKIE_FIELD_BROWSER_ID = 'identity'
const.COOKIE_FIELD_VOTER_ID = 'voterId'
const.COOKIE_FIELD_VOTER_CITY = 'voterCity'
const.COOKIE_FIELD_RECENTS = 'recent'

const.PRO = 'pro'
const.CON = 'con'

const.CHANGE_CREATE_SURVEY = 'CHANGE_CREATE_SURVEY'
const.CHANGE_FREEZE_USER_INPUT = 'CHANGE_FREEZE_USER_INPUT'
const.CHANGE_THAW_USER_INPUT = 'CHANGE_THAW_USER_INPUT'
const.CHANGE_FREEZE_NEW_PROPOSALS = 'CHANGE_FREEZE_NEW_PROPOSALS'
const.CHANGE_THAW_NEW_PROPOSALS = 'CHANGE_THAW_NEW_PROPOSALS'


# Login parameters
const.LOGIN_URL = 'https://openvoterid.net/login'
const.VOTER_ID_TIMEOUT_SEC = 600   # 10 minutes
const.VOTER_ID_LOGIN_SIG_LENGTH = 30
const.VOTER_ID_LOGIN_REQUEST_ID_LENGTH = 30

# Content lengths
const.minLengthSurveyIntro = 30
const.maxLengthSurveyIntro = 10000
const.minLengthQuestion = 30
const.maxLengthQuestion = 3000
const.minLengthAnswer = 1
const.minLengthRequest = 30
const.minLengthProposal = 30
const.minLengthReason = 20
const.maxLengthReason = 2000

const.CHAR_LENGTH_UNIT = 100

const.recentRequestsMax = 10

const.MAX_TOP_REASONS = 6

const.MAX_IMAGE_WIDTH = 1024
const.MAX_IMAGE_PIXELS = 512 * 1024;
const.MAX_IMAGE_BYTES = 5 * 1024 * 1024;  # 5MB upload limit
const.STORAGE_BUCKET_IMAGES = 'survey_option_images'
const.IMAGE_PATH = 'https://storage.googleapis.com/' + const.STORAGE_BUCKET_IMAGES  if const.IS_CLOUD  else '/image'

# HTTP/JSON request response codes
const.TOO_MANY_QUESTIONS = 'TOO_MANY_QUESTIONS'
const.TOO_MANY_OPTIONS = 'TOO_MANY_OPTIONS'
const.WRONG_TYPE = 'WRONG_TYPE'
const.UNCHANGED = 'UNCHANGED'
const.OUT_OF_RANGE = 'OUT_OF_RANGE'
const.TOO_SHORT = 'TOO_SHORT'
const.TOO_LONG = 'TOO_LONG'
const.REASON_TOO_SHORT = 'REASON_TOO_SHORT'
const.DUPLICATE = 'DUPLICATE'
const.BAD_CRUMB = 'BAD_CRUMB'
const.NO_COOKIE = 'NO_COOKIE'
const.NO_LOGIN = 'NO_LOGIN'
const.BAD_LINK = 'BAD_LINK'
const.NOT_OWNER = 'NOT_OWNER'
const.NOT_HOST = 'NOT_HOST'
const.HAS_RESPONSES = 'HAS_RESPONSES'
const.FROZEN = 'FROZEN'
const.EXPERIMENT_NOT_AUTHORIZED = 'EXPERIMENT_NOT_AUTHORIZED'
const.ERROR_DUPLICATE = 'ERROR_DUPLICATE'

# Persistent record class names
const.USER_CLASS_NAME = 'User'
const.LINK_KEY_CLASS_NAME = 'LinkKey'

# Environment variable names
const.REQUEST_LOG_ID = 'REQUEST_LOG_ID'


const.MAX_WORDS_INDEXED = 20

const.STOP_WORDS = [
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "am",
    "an",
    "and",
    "any",
    "are",
    "aren't",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "can't",
    "cannot",
    "could",
    "couldn't",
    "did",
    "didn't",
    "do",
    "does",
    "doesn't",
    "doing",
    "don't",
    "down",
    "during",
    "each",
    "few",
    "for",
    "from",
    "further",
    "had",
    "hadn't",
    "has",
    "hasn't",
    "have",
    "haven't",
    "having",
    "he",
    "he'd",
    "he'll",
    "he's",
    "her",
    "here",
    "here's",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "how's",
    "i",
    "i'd",
    "i'll",
    "i'm",
    "i've",
    "if",
    "in",
    "into",
    "is",
    "isn't",
    "it",
    "it's",
    "its",
    "itself",
    "let's",
    "me",
    "more",
    "most",
    "mustn't",
    "my",
    "myself",
    "nor",
    "not",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "ought",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "same",
    "shan't",
    "she",
    "she'd",
    "she'll",
    "she's",
    "should",
    "shouldn't",
    "so",
    "some",
    "such",
    "than",
    "that",
    "that's",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "there's",
    "these",
    "they",
    "they'd",
    "they'll",
    "they're",
    "they've",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "wasn't",
    "we",
    "we'd",
    "we'll",
    "we're",
    "we've",
    "were",
    "weren't",
    "what",
    "what's",
    "when",
    "when's",
    "where",
    "where's",
    "which",
    "while",
    "who",
    "who's",
    "whom",
    "why",
    "why's",
    "with",
    "won't",
    "would",
    "wouldn't",
    "you",
    "you'd",
    "you'll",
    "you're",
    "you've",
    "your",
    "yours",
    "yourself",
    "yourselves"
]

const.STOP_WORDS_SET = set( const.STOP_WORDS )

