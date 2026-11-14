from .config import client

def get_all(database, collection, query):
    db = client[database]
    collection = db[collection]
    return list(collection.find(query))
    
def get(database, collection, query):
    db = client[database]
    collection = db[collection]
    return collection.find_one(query)

def update(database, collection, query, data):
    db = client[database]
    collection = db[collection]
    collection.update_one(query, data)

def add(database, collection, data):
    db = client[database]
    collection = db[collection]
    collection.insert_one(data)

def delete(database, collection, query):
    db = client[database]
    collection = db[collection]
    collection.delete_one(query)

def delete_many(database, collection, query):
    db = client[database]
    collection = db[collection]
    collection.delete_many(query)