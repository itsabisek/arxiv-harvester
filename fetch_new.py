import requests
import feedparser
import time
import sys
from datetime import datetime
import pymongo as mongo
from urllib.parse import quote_plus


class Parser:

    def __init__(self, category, start_index=0, papers_per_call=1000, sleep_time=15, replace_version=True):
        self.base_url = 'http://export.arxiv.org/api/query?'
        # self.search_query = 'cat:cs.CV+OR+cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL+OR+cat:cs.NE+OR+cat:stat.ML'
        self.category = category
        self.papers_per_call = papers_per_call
        self.start_index = start_index
        self.sleep_time = sleep_time
        self.paper_versions = {}
        self.available_ids = set()
        self.papers_in_db = []
        self.replaceVersion = replace_version
        self.counter = 10
        self.connection = None
        self.updated = False

    def start(self, start_index=0):
        start_index = start_index
        username = quote_plus("abisek")
        password = quote_plus("abisek24")
        mongo_string = 'mongodb+srv://%s:%s@cluster0-fiaze.mongodb.net/arxivdl?authSource=admin&retryWrites=true&w' \
                       '=majority' % (username, password)

        print("Initializing database connection")
        self.connection = mongo.MongoClient(mongo_string)
        print("Connection Established. Fetching metadata...")
        metadata = self.connection.get_database('arxivdb').get_collection('metadata')

        cursor = metadata.find()
        print(f"Found {cursor.count()} in database")
        for entry in cursor:
            self.available_ids.add(entry['paper_id'])
            self.paper_versions[entry['paper_id']] = entry['paper_version']

        while True:
            papers = self.fetch(start_index)
            print(f"{len(papers)} fetched. Index : {start_index}")

            if len(papers) == 0:
                if self.counter != 0:
                    self.counter -= 1
                    self.pause()
                    continue
                else:
                    print("Max attempts reached. Stopping....")
                    return

            if len(papers) < self.papers_per_call:
                if self.counter != 0:
                    self.counter -= 1
                    print(f"Got less than {self.papers_per_call}.Pausing....")
                    self.pause()
                    continue
                else:
                    print("No more papers to fetch. Stopping....")
                    self.papers_in_db.extend(papers)
                    return

            self.papers_in_db.extend(papers)
            start_index += self.papers_per_call

            if self.counter != 10:
                self.counter = 10

    def fetch(self, start_index):
        base_url = self.base_url
        query_string = f"search_query=cat:{self.category}&start={start_index}&sortBy=lastUpdatedDate&" \
            f"max_results={self.papers_per_call}"
        final_url = base_url + query_string

        # print(final_url)
        response = requests.get(final_url)
        if response.status_code != 200:
            raise InvalidResponse("Got 404 Status Code")

        return self.parse(response.text)

    def parse(self, response):
        papers = []
        parsed_response = feedparser.parse(response)

        if len(parsed_response.entries) == 0:
            return papers

        for entry in parsed_response.entries:
            link = entry['links'][-1]['href']
            _id, version = link.split('/')[-1].split('v')

            if _id in self.available_ids and self.replaceVersion == False:
                continue
            tags = [tag['term'] for tag in entry.tags]
            authors = [author['name'] for author in entry['authors']]
            published_date = entry['published']
            updated_date = entry['updated']
            summary = entry['summary']
            title = entry['title']

            papers.append({'paper_id': _id,
                           'title': title,
                           'version': int(version),
                           'summary': summary,
                           'authors': authors,
                           'link': link,
                           'tags': tags,
                           'published_date': datetime.strptime(published_date, '%Y-%m-%dT%H:%M:%SZ'),
                           'updated_date': datetime.strptime(updated_date, '%Y-%m-%dT%H:%M:%SZ')})

            self.paper_versions[_id] = version

        return papers

    def updateToDb(self):
        if len(self.papers_in_db) != 0:
            papers = self.connection.get_database('arxivdl').get_collection('papers')
            results = papers.insert_many(self.papers_in_db)
            print(f"Updated {len(results.inserted_ids)}")
            self.updated = True

    def update_metadata(self):
        if self.connection is not None:
            if len(self.paper_versions) != 0:
                metadata = self.connection.get_database('arxivdl').get_collection('metadata')
                data = [{'paper_id': paper_id, 'paper_version': paper_version} for paper_id, paper_version in
                        self.paper_versions.items()]
                results = metadata.insert_many(data)

    def pause(self):
        print(f"Fetching Paused due to rate limiting.Sleeping for {self.counter} minutes")
        minutes = self.counter
        seconds = 0
        while minutes != -1:
            print("\n")
            sys.stdout.write(f"\rTime left : {minutes:02d}:{seconds:02d}")
            time.sleep(1)
            if seconds == 0:
                minutes -= 1
                seconds = 59
            else:
                seconds -= 1
        print("\n")

    def stop(self):
        print('Updating metadata to database')
        self.update_metadata()
        print("Closing database connections")
        if self.connection is not None:
            self.connection.close()


class InvalidResponse(Exception):
    pass
