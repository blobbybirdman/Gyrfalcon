from __future__ import print_function
import datetime
from datetime import date
import mysql.connector
from mysql.connector import errorcode
import csv

DB_NAME = 'tree_of_life'
DB_SOURCE = 'MyEbirdData.csv'

TABLES = {}
TABLES["bird_sightings"] = \
    """CREATE TABLE ebird (
    id varchar(20) NOT NULL,
    common_name varchar(100) NOT NULL,
    genus varchar(50) NOT NULL,
    species varchar(50) NOT NULL,
    subspecies varchar(50),
    taxon_order varchar(50),
    count varchar(10) NOT NULL, 
    state varchar(10) NOT NULL, 
    county varchar(50) NOT NULL, 
    location varchar(100) NOT NULL, 
    latitude float NOT NULL,
    longitude float NOT NULL, 
    date date NOT NULL,
    time time,
    protocol varchar(30), 
    duration int unsigned,
    distance int unsigned,
    area int unsigned, 
    num_obs int unsigned,
    breeding_code varchar(20),
    PRIMARY KEY (id, genus, species, subspecies)
    ) """


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
            print("Failed to create table: : ", name)
            print(err.msg)
    else:
        print("OK")

def processLine(fields):
    print(fields)
    record = {}
    
    #fields = line.split(',')
    record['id'] = fields[0]
    record['common'] = fields[1]
    sci = fields[2].split()
    record['genus'] = sci[0]
    record['species'] = sci[1]
    record['sub'] = 'NULL'
    if len(sci) > 2:
        record['sub'] = sci[2]
    record['order'] = fields[3]
    record['count'] = fields[4]
    record['state'] = fields[5]
    record['county'] = fields[6]
    record['location'] = fields[7]
    record['latitude'] = fields[8]
    record['longitude'] = fields[9]
    record['date'] = fields[10]
    record['time'] = fields[11]
    record['protocol'] = fields[12]
    record['duration'] = None
    if len(fields) > 13:
        if fields[13]:
            record['duration'] = fields[13]
    record['distance'] = None
    if len(fields) > 14:
        if fields[14]:
            record['distance'] = fields[14]
    record['area'] = None
    if len(fields) > 15:
        if fields[15]:
            record['area'] = fields[15]
    record['num_obs'] = None
    if len(fields) > 16:
        if fields[16]:
            record['num_obs'] = fields[16]
    record['breeding_code'] = None
    if len(fields) > 17:
        if fields[17]:
            record['breeding_code'] = fields[17]
    return record

def processCSVFile(f1, cursor):
    csvFile = open(f1, 'r')
    csvFile.readline()[:5]

    reader = csv.reader(csvFile, delimiter=',', quotechar='"')
    for row in reader:
        record = processLine(row)
        addRecord(record, cursor)
    
    #for line in csv.readlines():
    #    record = processLine(line[:-1])
    #    addRecord(record, cursor)

def addRecord(record, cursor):
    print(record['common'])
    addrecord = ("INSERT INTO ebird "
               "(id, common_name, genus, species, subspecies, taxon_order, count, "
               "state, county, location, latitude, longitude, date, time, protocol, "
               "duration, distance, area, num_obs, breeding_code) "
               "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
    date_fields = record['date'].split('-')
    year = int(date_fields[2])
    month = int(date_fields[0])
    day = int(date_fields[1])
    obs_time = None
    if record['time']:
        time_fields = record['time'].split()
        hours, mins = time_fields[0].split(':')
        hours = int(hours)
        mins = int(mins)
        if time_fields[1] == 'PM' and hours < 12:
            hours += 12
        obs_time = datetime.time(hours, mins)
    data = (record['id'], record['common'], record['genus'], record['species'], record['sub'], record['order'], record['count'], record['state'], \
                record['county'], record['location'], record['latitude'], record['longitude'], date(year, month, day), obs_time, record['protocol'], \
                record['duration'], record['distance'], record['area'], record['num_obs'], record['breeding_code'])
    print(data)
    cursor.execute(addrecord, data)

processCSVFile(DB_SOURCE, cursor)

cnx.commit()
cursor.close()
cnx.close()
