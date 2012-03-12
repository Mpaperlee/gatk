import os.path
import sys
from optparse import OptionParser
from itertools import *
from xml.etree.cElementTree import *
import gzip
import datetime
import re
import MySQLdb
import unittest
import traceback

MISSING_VALUE = "NA"
RUN_REPORT_LIST = "GATK-run-reports"
RUN_REPORT = "GATK-run-report"

def main():
    global OPTIONS
    usage = "usage: %prog [options] mode file1 ... fileN"
    parser = OptionParser(usage=usage)
    
    parser.add_option("-v", "--verbose", dest="verbose",
                        action='store_true', default=False,
                        help="If provided, verbose progress will be enabled")         

    parser.add_option("", "--overwrite", dest="overwrite",
                        action='store_true', default=False,
                        help="If provided, archive mode will overwrite destination file, if it exists (DANGEROUS)")         

    parser.add_option("-o", "--o", dest="output",
                        type='string', default=None,
                        help="if provided, output will go here instead of stdout")

    parser.add_option("-i", "", dest="ID",
                        type='string', default=None,
                        help="if provided, only process the record with this id")

    parser.add_option("-M", "--maxRecords", dest="maxRecords",
                        type='int', default=None,
                        help="if provided, only the first maxRecords records will be processed")

    parser.add_option("", "--no-dev", dest="noDev",
                        action='store_true', default=False,
                        help="if provided, only records not coming from a dev version of GATK will be included")

    parser.add_option("", "--rev", dest="rev",
                        type="string", default=None,
                        help="if provided, only reports generated by this version of the GATK will be included")

    parser.add_option("-E", "", dest="exception_selection",
                        type='choice', choices=['all', 'user', 'sting'], default='all',
                        help="if provided, will only emit records matching of the provided class [default %default]")

    parser.add_option("-n", "--dry-run", dest="dryRun",
                        action='store_true', default=False,
                        help="Don't submit to the DB")

    parser.add_option("-t", "--test", dest="test",
                        action='store_true', default=False,
                        help="Run unit tests")

    parser.add_option("", "--versions", dest="versions",
                        type='string', default="/humgen/gsa-hpprojects/GATK/data/git.versions",
                        help="If provided, reads in GATK version information from the file")

    parser.add_option("", "--dbTable", dest="dbTable",
                        type='string', default="gatk",
                        help="The name of the SQL DB to use")

    parser.add_option("", "--max_days", dest="maxDays",
                        type='int', default=None,
                        help="if provided, only records generated within X days of today will be included")
    parser.add_option("", "--updateFreq", dest="updateFreq",
                        type='int', default=-1,
                        help="if provided, print progress every updateFreq records")
    parser.add_option("-D", "--delete_while_archiving", dest="reallyDeleteInArchiveMode",
                        action='store_true', default=False,
                        help="if provided, we'll actually delete records when running in archive mode")
         
    (OPTIONS, args) = parser.parse_args()
    if len(args) == 0:
        parser.error("Requires at least GATKRunReport xml to analyze")

    if OPTIONS.test:
        sys.argv = ["x"]
        unittest.main()
        return

    stage = args[0]
    files = resolveFiles(args[1:])
    
    if os.path.exists(OPTIONS.versions):
        OPTIONS.versions = read_versions(OPTIONS.versions)
    else:
        OPTIONS.versions = dict()
        print 'Warning: git version file does not exist', OPTIONS.versions

    # open up the output file
    if OPTIONS.output != None:
        if stage == "archive" and os.path.exists(OPTIONS.output) and not OPTIONS.overwrite:
            raise "archive output file already exists, aborting!", OPTIONS.output
        out = openFile(OPTIONS.output,'w')
    else:
        out = sys.stdout

    handler = getHandler(stage)(stage, out)
    handler.initialize(files)

    # parse all of the incoming files
    counter = 0
    for report in readReports(files):
        # todo -- add matching here
        ID = report.find('id').text
        if OPTIONS.ID == None or ID == OPTIONS.ID:
            handler.processRecord(report)
            counter += 1
            report.clear()
            if OPTIONS.updateFreq > 0 and counter % OPTIONS.updateFreq == 0: 
                print 'Processed records:', counter 
            if OPTIONS.maxRecords > 0 and counter > OPTIONS.maxRecords: 
                break

    handler.finalize(files)
    if OPTIONS.output != None: out.close()
    print 'Processed records:', counter 

# -When you check which repo(s) a version number belongs to, there are 3 possibilities:
# 
#       * The version exists in github only: it's a publicly-released version that lacks private data
#       * The version exists in both stable and unstable, but not github: it's a non-public stable version.
#       * The version exists in unstable only: it's an unstable version (obviously).

# file looks like
#
# type unstable
# 1.4-371-g3f76265
# 1.4-28-g26ab3e8
# type stable
# 1.4-28-g26ab3e8
# 1.4-27-g15c5b7a
# type gatk.git
# 1.4-28-g7dc6f73
# 1.4-27-gd5fce22
#
# created with script private/shell/gitVersionNumbers.csh
def read_versions(file):
    d = dict()
    type = None
    for line in open(file):
        line = line.strip()
        vals = line.split()
        if vals[0] == "type":
            type = vals[1]
        else: 
            if line not in d:
                d[line] = list()
            d[line].append(type)
    
    # assigns specific release structure to everything.  can be release, stable, unstable, or unknown
    def resolveType(version, types):
        type = "unknown"
        if len(types) > 3:
            raise 'Unexpected number of types', types
        elif len(types) == 3:
            #print version, types
            type = "gatk.git" # must be the same name as the release repo
        elif len(types) == 2:
            if 'stable' not in types:
                raise 'Unexpected combination: ' + str(types)
            #print version, types
            type = "stable"
        else: 
            type = types[0]
        return type

    return dict([[version, resolveType(version, types)] for version, types in d.iteritems()])  

#
# Stage HANDLERS
#
class StageHandler:
    def __init__(self, name, out):
        self.name = name
        self.out = out
        
    def getName(self): return self.name
        
    def initialize(self, args):
        pass # print 'initialize'
        
    def processRecord(self, record):
        pass # print 'processing record', record
        
    def finalize(self, args):
        pass # print 'Finalize'


# a map from stage strings -> function to handle record
HANDLERS = dict()
def addHandler(name, handler):
    HANDLERS[name] = handler
    
def getHandler(stage):
    return HANDLERS[stage]

def eltIsException(elt):
    return elt.tag == "exception"
    
RUN_STATUS_SUCCESS = "success"
def parseException(elt):
    msgElt = elt.find("message")
    msgText = "MISSING"
    userException = "NA"
    stackTraceString = "NA"
    runStatus = RUN_STATUS_SUCCESS
    if msgElt != None: 
        msgText = msgElt.text
        runStatus = "sting-exception"
    
    stackTrace = elt.find("stacktrace")
    if stackTrace != None:
        strings = stackTrace.findall("string")
        if len(strings) > 0:
            stackTraceString = '\n'.join(map(lambda x: x.text, strings))
    
    if elt.find("is-user-exception") != None:
        #print elt.find("is-user-exception")
        userException = elt.find("is-user-exception").text
        if userException == "true": runStatus = "user-exception"
    #if runStatus != "completed": print stackTrace, elt.find('stacktrace')
    return msgText, stackTraceString, userException, runStatus

def javaExceptionFile(javaException):
    m = re.search("\((.*\.java:.*)\)", javaException)
    if m != None:
        return m.group(1)
    else:
        return javaException
        
def parseGATKVersion(text):
    # maps svn numbers 1.0.Vxxx to 0.V.xxx
    svnMatch = re.match("^1\.0\.(\d)(\d*)", text)
    major = "unknown"
    minor = "0"
    if svnMatch != None:
        major = "0.%s" % svnMatch.group(1)
        minor = svnMatch.group(2)
    else:
        # maps git numbers 1.3-22-g1bfe280 to 1.3
        gitFullMatch = re.match("^(\d)\.(\d+)-(\d+)-\w*$", text)
        if gitFullMatch != None:
            major = "%s.%s" % gitFullMatch.group(1,2)
            minor = gitFullMatch.group(3)
        else:
            gitShortMatch = re.match("^(\d)\.(\d+)$", text)
            if gitShortMatch != None:
                major = "%s.%s" % gitShortMatch.group(1,2)
            
    #print text, "=>", major, minor
    return major, int(minor)

class TestSequenceFunctions(unittest.TestCase):
    def setUp(self):
        self.data = {
            "1.0.5777" : ['0.5', 777],
            "1.0.6000" : ['0.6', 0],
            "1.3-33-g1bfe280" : ['1.3', 33],
            "1.4-1-xafdasdf" : ['1.4', 1],
            "1.3" : ['1.3', 0],
            "<unknown>" : ['unknown', 0],
            "382343549e2e98e2727e66548b6b2bafa6fa4297" : ['unknown', 0]
            }

    def test_parsing(self):
        for versionString, expectedResult in self.data.iteritems():
            parsed = parseGATKVersion(versionString)
            print '%s : expected= %s observed = %s' % (versionString, str(expectedResult), str(parsed))
            self.assertEquals(parsed[0], expectedResult[0])
            self.assertEquals(parsed[1], expectedResult[1])

class RecordDecoder:
    def __init__(self):
        self.fields = list()
        self.formatters = dict()
    
        def id(elt): return elt.text
        def toString(elt): return '%s' % elt.text

        def formatMajorVersion(elt):
            return parseGATKVersion(elt.text)[0]

        def formatMinorVersion(elt):
            return str(parseGATKVersion(elt.text)[1])

        def formatReleaseType(elt):
            if elt.text not in OPTIONS.versions:
                #print 'release-type', elt.text
                type = "unknown"
            else:
                type = OPTIONS.versions[elt.text]
            return type
            
        def formatExceptionMsg(elt):
            return '%s' % parseException(elt)[0]

        def formatExceptionAt(elt):
            return '%s' % parseException(elt)[1]

        def formatExceptionAtBrief(elt):
            return '%s' % javaExceptionFile(parseException(elt)[1])
            
        def formatExceptionUser(elt):
            return '%s' % parseException(elt)[2]

        def formatRunStatus(elt):
            #print 'formatRunStatus', parseException(elt)
            return parseException(elt)[3]

        def formatHostName(elt):
            if elt != None and elt.text != None:
                return elt.text
            else:
                return 'unknown'
            
        def formatDomainName(elt):
            hostname = formatHostName(elt)
            parts = hostname.split(".")
            if len(parts) >= 2:
                return '.'.join(parts[-2:])
            else:
                return 'unknown'
        
        def add(names, func):
            for name in names:
                addComplex(name, [name], [func])

        def addComplex(key, fields, funcs):
            self.fields.extend(fields)
            self.formatters[key] = zip(fields, funcs)
    
        add(["id", "walker-name"], id)
        addComplex("svn-version", ["svn-version", "gatk-version", "gatk-minor-version", "release-type"], [id, formatMajorVersion, formatMinorVersion, formatReleaseType])
        add(["start-time", "end-time"], toString)      
        add(["run-time", "user-name"], id)
        addComplex("host-name", ["host-name", "domain-name"], [formatHostName, formatDomainName])
        add(["java", "machine"], toString)
        add(["max-memory", "total-memory", "iterations"], id)
        addComplex("exception", ["exception-msg", "stacktrace", "exception-at-brief", "is-user-exception", "run-status"], [formatExceptionMsg, formatExceptionAt, formatExceptionAtBrief, formatExceptionUser, formatRunStatus])
        #add(["command-line"], toString)          
        
    def decode(self, report):
        bindings = dict()
        for elt in report:
            if elt.tag in self.formatters:
                fieldFormats = self.formatters[elt.tag]
                # we actually care about this tag
                for field, formatter in fieldFormats:
                    bindings[field] = formatter(elt)

        # add missing data
        for field in self.fields:
            if field not in bindings:
                bindings[field] = MISSING_VALUE

        return bindings

# def 
class AbstractRecordAsTable(StageHandler):
    def __init__(self, name, out):
        StageHandler.__init__(self, name, out)
        
    def initialize(self, args):
        self.decoder = RecordDecoder()
        print >> self.out, "\t".join(self.getFields())
        
    def getFields(self):
        raise Expection("Abstract class cannot be run directly")

    def processRecord(self, record):
        try:
            parsed = self.decoder.decode(record)

            def oneField(field):
                val = MISSING_VALUE
                if field in parsed:
                    val = parsed[field]
                    if val == None:
                        if OPTIONS.verbose: print >> sys.stderr, 'field', field, 'is missing in', parsed['id']
                    else:
                        val = val.replace('"',"'")
                        if val.find(" ") != -1:
                            val = "\"" + val + "\""
                return val
            
            print >> self.out, "\t".join([ oneField(field) for field in self.getFields() ])
        except:
            #print 'Failed to convert to table ', parsed
            print 'Failed to convert to table', record
            pass
    
# def 
class RecordAsTable(AbstractRecordAsTable):
    def __init__(self, name, out):
        AbstractRecordAsTable.__init__(self, name, out)

    def getFields(self):
        return self.decoder.fields
            
addHandler('table', RecordAsTable)

class RecordAsMinimalTable(AbstractRecordAsTable):
    FIELDS_TO_TAKE = ['walker-name', "start-time", "run-time", "host-name"]
    def __init__(self, name, out):
        AbstractRecordAsTable.__init__(self, name, out)

    def getFields(self):
        return self.FIELDS_TO_TAKE
            
addHandler('minimaltable', RecordAsMinimalTable)

class CountRecords(StageHandler):
    def __init__(self, name, out):
        StageHandler.__init__(self, name, out)
        
    def initialize(self, args):
        self.counter = 0

    def processRecord(self, record):
        self.counter += 1

addHandler('count', CountRecords)


class RecordAsXML(StageHandler):
    def __init__(self, name, out):
        StageHandler.__init__(self, name, out)

    def initialize(self, args):
        print >> self.out, "<%s>" % RUN_REPORT_LIST
        
    def processRecord(self, record):
        print >> self.out, tostring(record)

    def finalize(self, args):
        print >> self.out, "</%s>" % RUN_REPORT_LIST

addHandler('xml', RecordAsXML)

class Archive(RecordAsXML):
    def __init__(self, name, out):
        RecordAsXML.__init__(self, name, out)

    def finalize(self, args):
        RecordAsXML.finalize(self, args)
        for arg in args:
            if OPTIONS.verbose: print 'Deleting file: ', arg
            if OPTIONS.reallyDeleteInArchiveMode:
                os.remove(arg)
        print 'Deleted', len(args), 'files'
        
addHandler('archive', Archive)

class ExceptionReport(StageHandler):
    #FIELDS = ["Msg", "At", "SVN.versions", "Walkers", 'Occurrences', 'IDs']
    def __init__(self, name, out):
        StageHandler.__init__(self, name, out)
        self.exceptions = []

    def initialize(self, args):
        self.decoder = RecordDecoder()
        #print >> self.out, "\t".join(self.FIELDS)
        
    def processRecord(self, record):
        for elt in record:
            if eltIsException(elt):
                self.exceptions.append(self.decoder.decode(record))
                break

    def finalize(self, args):
        commonExceptions = list()
        
        def addToCommons(ex):
            for common in commonExceptions:
                if common.equals(ex):
                    common.update(ex)
                    return
            commonExceptions.append(CommonException(ex))

        for ex in self.exceptions:
            addToCommons(ex)
        commonExceptions = sorted(commonExceptions, None, lambda x: x.counts)   
            
        for common in commonExceptions:
            msg, at, svns, walkers, counts, ids, duration, users, userError = common.toStrings()
            
            if not matchesExceptionSelection(userError):
                continue
                
            print >> self.out, ''.join(['*'] * 80)
            print >> self.out, 'Exception              :', msg
            print >> self.out, '    is-user-exception? :', userError
            print >> self.out, '    at                 :', at
            print >> self.out, '    walkers            :', walkers
            print >> self.out, '    svns               :', svns
            print >> self.out, '    duration           :', duration
            print >> self.out, '    occurrences        :', counts
            print >> self.out, '    users              :', users
            print >> self.out, '    ids                :', ids
            

def matchesExceptionSelection(userError):
    if OPTIONS.exception_selection == "all":
        return True
    elif OPTIONS.exception_selection == "user" and userError == "true":
        return True
    elif OPTIONS.exception_selection == "sting" and userError == "false":
        return True
    return False
    
class CommonException:
    MAX_SET_ITEMS_TO_SHOW = 5

    def __init__(self, ex):
        self.msgs = set([ex['exception-msg']])
        self.at = ex['stacktrace']
        self.svns = set([ex['svn-version']])
        self.users = set([ex['user-name']])
        self.userError = ex['is-user-exception']
        self.counts = 1
        self.times = set([decodeTime(ex['end-time'])])
        self.walkers = set([ex['walker-name']])
        self.ids = set([ex['id']])
        
    def equals(self, ex):
        return self.at == ex['stacktrace']
        
    def update(self, ex):
        self.msgs.add(ex['exception-msg'])
        self.svns.add(ex['svn-version'])
        self.users.add(ex['user-name'])
        self.counts += 1
        self.walkers.add(ex['walker-name'])
        self.times.add(decodeTime(ex['end-time']))
        self.ids.add(ex['id'])

    def bestExample(self, examples):
        def takeShorter(x, y):
            if len(y) < len(x):
                return y
            else:
                return x
        return reduce(takeShorter, examples)
        
    def setString(self, s):
        if len(s) > self.MAX_SET_ITEMS_TO_SHOW:
            s = [x for x in s][0:self.MAX_SET_ITEMS_TO_SHOW] + ["..."]
        return ','.join(s)
        
    def duration(self):
        x = sorted(filter(lambda x: x != "ND", self.times))
        if len(x) >= 2:
            return "-".join(map(lambda x: x.strftime("%m/%d/%y"), [x[0], x[-1]]))
        elif len(x) == 1:
            return x[0]
        else:
            return "ND"
            
        
    def toStrings(self):
        return [self.bestExample(self.msgs), self.at, self.setString(self.svns), self.setString(self.walkers), self.counts, self.setString(self.ids), self.duration(), self.setString(self.users), self.userError] 

addHandler('exceptions', ExceptionReport)

  
  
class SummaryReport(StageHandler):
    #FIELDS = ["Msg", "At", "SVN.versions", "Walkers", 'Occurrences', 'IDs']
    def __init__(self, name, out):
        StageHandler.__init__(self, name, out)
        self.reports = []

    def initialize(self, args):
        self.decoder = RecordDecoder()
        #print >> self.out, "\t".join(self.FIELDS)
        
    def processRecord(self, record):
        self.reports.append(self.decoder.decode(record))

    def finalize(self, args):
        print >> self.out, 'GATK run summary for          :', datetime.datetime.today()
        print >> self.out, '    number of runs            :', len(self.reports)
        print >> self.out, '    number of StingExceptions :', len(filter(isStingException, self.reports))
        print >> self.out, '    number of UserExceptions  :', len(filter(isUserException, self.reports))
        print >> self.out, '    users                     :', ', '.join(set(map(userID, self.reports)))

def userID(rec):
    return rec['user-name']

def isStingException(rec):
    return rec['stacktrace'] != "NA" and rec['is-user-exception'] == "false"

def isUserException(rec):
    return rec['stacktrace'] != "NA" and rec['is-user-exception'] == "true"

addHandler('summary', SummaryReport)  
  
# def 
DB_EXISTS = True
class SQLRecordHandler(StageHandler):
    def __init__(self, name, out):
        StageHandler.__init__(self, name, out)
        
    def initialize(self, args):
        self.decoder = RecordDecoder()
        self.name = "GATK_LOGS"

        host = "calcium.broadinstitute.org"
        db = OPTIONS.dbTable
        print 'Connecting to SQL server', host, 'using DB', db
        if DB_EXISTS and not OPTIONS.dryRun: 
            self.db = MySQLdb.connect( host=host, db=db, user="gsamember", passwd="gsamember" )
        if DB_EXISTS and not OPTIONS.dryRun: 
            self.dbc = self.db.cursor() 

    def processRecord(self, record):
        pass

    def getFields(self):
        return ["id", "walker-name", "gatk-version", 
                "gatk-minor-version", "svn-version", 
                "start-time", "end-time", "run-time", 
                "user-name", "host-name", "domain-name", 
                "total-memory", "stacktrace", "exception-at-brief", 
                "exception-msg", "is-user-exception", 
                "run-status", "release-type"]
        
    def finalize(self, args):
        if DB_EXISTS and not OPTIONS.dryRun: 
            self.dbc.close()
            self.db.close()
        
    def execute(self, command):
        if OPTIONS.verbose: print "EXECUTING: ", command
        if DB_EXISTS and not OPTIONS.dryRun: 
            self.dbc.execute(command)
        if OPTIONS.verbose: print '  DONE'        

class InsertRecordIntoTable(SQLRecordHandler):
    def __init__(self, name, out):
        SQLRecordHandler.__init__(self, name, out)
        
    def processRecord(self, record):
        id = 'unknown'
        try:
            parsed = self.decoder.decode(record)
            id = parsed['id']
            
            def oneField(field):
                val = MISSING_VALUE
                if field in parsed:
                    val = parsed[field]
                    if val == None:
                        if OPTIONS.verbose: print >> sys.stderr, 'field', field, 'is missing in', parsed['id']
                    else:
                        if field == "run-status" and val == MISSING_VALUE:
                            val = RUN_STATUS_SUCCESS
                        val = val.replace('"',"'")
                        #if val.find(" ") != -1:
                        val = "\"" + val + "\""

                return val

            values = [ oneField(field) for field in self.getFields() ]            
            #print >> self.out, "\t".join(values)
            
            self.execute("INSERT INTO " + self.name + " VALUES(" + ", ".join(values) + ")")
        except Exception, inst:
            print 'Skipping excepting record', id, inst
            if OPTIONS.verbose: 
                exc_type, exc_value, exc_traceback = sys.exc_info()
                traceback.print_exception(exc_type, exc_value, exc_traceback)
            pass

DEFAULT_SIZE = 128
SIZE_OVERRIDES = {
    "domain-name" : 256, 
    "exception-at-brief" : 1024, 
    "stacktrace" : 8192, 
    "exception-msg" : 2048, 
    "command-line" : 8192}            
class SQLSetupTable(SQLRecordHandler):
    def __init__(self, name, out):
        SQLRecordHandler.__init__(self, name, out)
        
    def initialize(self, args):
        SQLRecordHandler.initialize(self, args)

        self.execute("DROP TABLE " + self.name)
        self.execute("CREATE TABLE " + self.name + " (" + ", ".join(map(self.fieldDescription, self.getFields())) + ")")
        # initialize database
        SQLRecordHandler.finalize(self, args)
        sys.exit(0)

    def fieldDescription(self, field):
        desc = field.replace("-", "_")

        size = DEFAULT_SIZE
        #print 'field', field, SIZE_OVERRIDES
        if field in SIZE_OVERRIDES:
            size = SIZE_OVERRIDES[field]
        desc = desc + " VARCHAR(%d)" % size

        if field == "id":
            desc = desc + " PRIMARY KEY"

        return desc

addHandler('loadToDB', InsertRecordIntoTable)
addHandler('setupDB', SQLSetupTable)
        
#
# utilities
#
def openFile(filename, mode='r'):
    if ( filename.endswith(".gz") ):
        return gzip.open(filename, mode)
    else:
        return open(filename, mode)

def resolveFiles(paths):
    allFiles = list()
    def resolve1(path):
        if not os.path.exists(path):
            raise Exception("Path doesn't exist: " + path)
        elif os.path.isfile(path):
            allFiles.append(path)
        else:
            def one(arg, dirname, files):
                #print dirname, files
                #print dirname
                allFiles.extend(map( lambda x: os.path.join(path, x), files ))
                #print files
    
            os.path.walk(path, one, None)

    map( resolve1, paths )
    return allFiles

def decodeTime(time):
    if time == "ND":
        return "ND"
    else:
        return datetime.datetime.strptime(time.split()[0], "%Y/%m/%d")
    #return datetime.datetime.strptime(time, "%Y/%m/%d %H.%M.%S")

def eltTagEquals(elt, tag, value, startsWith = None):
    if elt == None:
        return False
    msgElt = elt.find(tag)
    #print msgElt, msgElt.text, startsWith
    found = msgElt != None and (msgElt.text == value or (startsWith == None or msgElt.text.startswith(startsWith)))
    #print 'finding', tag, 'in', elt, msgElt, msgElt.text, found
    return found

def passesFilters(elt):
    if OPTIONS.noDev and eltTagEquals(elt.find('argument-collection'),'phone-home-type','DEV'):
        #print 'skipping', elt
        return False
    if OPTIONS.rev != None and not eltTagEquals(elt, 'svn-version', None, startsWith=OPTIONS.rev):
        return False
    if OPTIONS.maxDays != None:
        now = datetime.datetime.today()
        now = datetime.datetime(now.year, now.month, now.day)
        #    <start-time>2010/08/31 15.38.00</start-time>
        eltTime = decodeTime(elt.find('end-time').text)
        diff = now - eltTime
        #print eltTime, now, diff, diff.days
        if diff.days > OPTIONS.maxDays:
            return False

    return True
    
def readReportsSlow(files):
    #print files
    for file in files:
        if OPTIONS.verbose: print 'Reading file', file
        input = openFile(file)
        try:
            tree = ElementTree(file=input)
        except:
            print "Ignoring excepting file", file
            continue

        elem = tree.getroot()
        if elem.tag == RUN_REPORT_LIST:
            counter = 0
            for sub in elem:
                if passesFilters(sub):
                    counter += 1
                    if counter % 1000 == 0: print 'Returning', counter
                    yield sub
        else:
            if passesFilters(elem):
                yield elem
    
def readReports(files):
    #print files
    for file in files:
        if OPTIONS.verbose: print 'Reading file', file
        input = openFile(file)
        try:
            counter = 0
            for event, elem in iterparse(input):
                if elem.tag == RUN_REPORT:
                    if passesFilters(elem):
                        counter += 1
                        #if counter % 1000 == 0: print 'Returning', counter
                        yield elem    
        except:
            print "Ignoring excepting file", file
            continue


if __name__ == "__main__":
    main()
