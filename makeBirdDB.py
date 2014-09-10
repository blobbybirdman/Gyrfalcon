from __future__ import print_function

import mysql.connector
from mysql.connector import errorcode

DB_NAME = 'tree_of_life'
DB_SOURCE = 'clements.csv'

TABLES = {}
TABLES['birds'] = (
    "CREATE TABLE 'birds' ("
    "  'id' int UNSIGNED NOT NULL,"
    "  'category' varchar(20) NOT NULL,"
    "  'genus' varchar(40) NOT NULL,"
    "  'species' varchar(40) NOT NULL,"
    "  'subspecies' varchar(40),"
    "  'group' varchar(40),"
    "  'english_name' varchar(50),"
    "  'range' varchar(200),"
    "  'order' varchar(40) NOT NULL,"
    "  'family' varchar(40) NOT NULL,"
    "  'family' varchar(40),"
    "  'extinct' enum('True', 'False') NOT NULL,"
    "  'extinct_date' year,"
    "  PRIMARY KEY ('id')"
    ") ENGINE=InnoDB")

print(TABLES['birds'])

config = {
    'user': 'root',
    'password': '',
    'host': '127.0.0.1',
    'database': None,
    'raise_on_warnings': True,
}

try:
    cnx = mysql.connector.connect(**config)
except mysql.connector.Error as err:
    if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
        print("Something is wrong with your user name or password")
    elif err.errno == errorcode.ER_BAD_DB_ERROR:
        print("Database does not exist")
    else:
        print(err)
        cnx.close()

cursor = cnx.cursor()

def create_database(cursor):
    try:
        cursor.execute("CREATE DATABASE {} DEFAULT CHARACTER SET 'utf8'".format(DB_NAME))
    except mysql.connector.Error as err:
        print("Failed creating database: {}".format(err))
        exit(1)

try:
    cnx.database = DB_NAME
except mysql.connector.Error as err:
    if err.errno == errorcode.ER_BAD_DB_ERROR:
        create_database(cursor)
        cnx.database = DB_NAME
    else:
        print(err)
        exit(1)

for name, ddl in TABLES.iteritems():
    try:
        print("Creating table {}: ".format(name), end='')
        cursor.execute(ddl)
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_TABLE_EXISTS_ERROR:
            print("already exists")
        else:
            print(err.msg)
    else:
        print("OK")

def processLine(line):
    record = {}
    fields = line.split(':')
    record['id'] = fields[0]
    cat = fields[3][1:-1]
    record['cat'] = cat
    sci = fields[4][1:-1].split()
    genus = sci[0]    
    record['genus'] = genus
    spec = sci[1]
    record['spec'] = spec
    record['sub'] = None
    record['group'] = None
    if cat in ['subspecies', 'group (monotypic)']:
        record['sub'] = sci[2]
    elif cat in ['group (polytypic)']:
        record['group'] = fields[4][len(genus)+len(spec)+4:-2]
    record['eng'] = fields[5][1:-1]
    record['rang'] = fields[6][1:-1]
    record['order'] = fields[7][1:-1]
    fam = fields[8][1:-1].split()
    family = fam[0]
    record['family'] = family
    record['fam_desc'] = fields[8][len(family)+2:-1]
    record['ext'] = fields[9]
    record['ext_date'] = fields[10]
    return record

def processCSVFile(f1, cursor):
    csv = open(f1, 'r')
    csv.readline()[:5]
    
    for line in csv.readlines():
        record = processLine(line)
        addRecord(record, cursor)

def addRecord(record, cursor):
    print(record['eng'])
    addBird = ("INSERT INTO birds "
               "(id) "
               "VALUES (%s)")
               #           "(id, category, genus, species, subspecies, english_name, range, order, family, family_desc, extinct, extinct_date) "
               #           "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
    extinct = 'False'
    if extinct == 1:
        print(record['eng'], "is extinct")
        extinct = "True"
    birdData = (record['id'])
    #birdData = (record['id'], record['cat'], record['genus'], record['spec'], record['sub'], record['eng'], \
    #            record['rang'], record['order'], record['family'], record['fam_desc'], extinct, record['ext_date'])
    
    print(addBird)
    print(birdData)
    cursor.execute(addBird, birdData)

processCSVFile(DB_SOURCE, cursor)

cnx.commit()
cursor.close()
cnx.close()
